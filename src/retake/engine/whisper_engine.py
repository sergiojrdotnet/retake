from __future__ import annotations

import ctypes
import importlib.util
import time
from pathlib import Path

import numpy as np


def available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def preload_cuda_libraries() -> list[str]:
    """ctranslate2 wheels link against CUDA 12 and cuDNN 9; on systems with another CUDA the
    pip-provided nvidia-* libraries must be loaded before ctranslate2 so the loader finds them."""
    loaded = []
    spec = importlib.util.find_spec("nvidia")
    if spec is None or not spec.submodule_search_locations:
        return loaded
    for root in spec.submodule_search_locations:
        for pattern in ("cublas/lib/libcublasLt.so.12", "cublas/lib/libcublas.so.12", "cudnn/lib/libcudnn*.so.9"):
            for library in sorted(Path(root).glob(pattern)):
                try:
                    ctypes.CDLL(str(library), mode=ctypes.RTLD_GLOBAL)
                    loaded.append(library.name)
                except OSError:
                    continue
    return loaded


def cuda_devices() -> int:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count()
    except Exception:
        return 0


def looks_hallucinated(text: str, compression_ratio: float, avg_logprob: float) -> bool:
    # On silence or noise Whisper tends to loop a phrase ("the time is now the time is now …").
    # These are the thresholds Whisper itself uses before retrying at a higher temperature.
    words = text.lower().split()
    if len(words) >= 8 and len(set(words)) <= len(words) / 4:
        return True
    return compression_ratio > 2.4 or avg_logprob < -1.0


class WhisperTranscriber:
    name = "faster-whisper"

    def __init__(self, model: str, download_root: Path, device: str = "auto", language: str = "en", threads: int = 4):
        if device != "cpu":
            preload_cuda_libraries()
        from faster_whisper import WhisperModel

        if device == "auto":
            device = "cuda" if cuda_devices() else "cpu"
        compute = "int8_float16" if device == "cuda" else "int8"
        self.device = device
        self.language = language
        self.model = WhisperModel(model, device=device, compute_type=compute, cpu_threads=threads, download_root=str(download_root))
        self.last_seconds = 0.0

    def transcribe(self, audio: np.ndarray, offset: float, prompt: str = "") -> list[dict]:
        started = time.perf_counter()
        samples = audio.astype(np.float32) / 32768.0
        segments, _ = self.model.transcribe(
            samples,
            language=self.language,
            beam_size=1,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt=prompt or None,
            word_timestamps=True,
            vad_filter=False,
            no_speech_threshold=0.6,
        )
        words = []
        for segment in segments:
            if segment.no_speech_prob > 0.8 or looks_hallucinated(segment.text, segment.compression_ratio, segment.avg_logprob):
                continue
            for word in segment.words or []:
                text = word.word.strip()
                if not text or word.probability < 0.2:
                    continue
                words.append({
                    "text": text,
                    "start": float(offset + word.start),
                    "end": float(offset + word.end),
                    "conf": float(word.probability),
                })
        self.last_seconds = time.perf_counter() - started
        return words
