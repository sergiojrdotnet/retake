from __future__ import annotations

import copy
import importlib.util
import os
import re
import tomllib
from pathlib import Path

import tomli_w

from . import paths
from .script.lexicon import atomic_write

DEFAULTS: dict = {
    "general": {
        "projects_dir": str(paths.default_projects_dir()),
        "script_language": "en",
        "native_language": "pt-BR",
        "ui_language": "auto",
        "recent_projects": [],
        "explorer": True,
        "layout": "full",
    },
    "audio": {"input": "default", "channels": "mix", "sample_rate": 0},
    "camera": {
        # none, device (a webcam or any video device) or phone (Android over USB, through scrcpy).
        "source": "none",
        "device": "",
        "codec": "auto",
    },
    # The phone camera; each phone can override these under phones.<adb serial>.
    "phone": {
        "serial": "",
        "camera": "back",
        "size": "3840x2160",
        "fps": 30,
        "codec": "h265",
        "bitrate": "40M",
        "container": "mkv",
        "shape": "landscape",
        "flip": False,
        "preview": False,
    },
    "engines": {
        "preset": "auto",
        "device": "auto",
        "vad": "auto",
        "tracking": "auto",
        "whisper_model": "small.en",
        "commands": True,
        "scorer": "auto",
        "tts": "auto",
        "threads": 4,
    },
    "coach": {"enabled": True, "threshold": 55.0, "require": 0, "drill_times": 3, "timing": "live", "auto_flag_misses": 3},
    "strictness": {"extra_speech": "between", "deviations": "warn"},
    "guides": {"ipa": False, "respell": True, "native": True, "scope": "hard"},
    "prompter": {
        "mode": "scroll",
        "font_size": 44,
        "line_width": 0.82,
        "reading_line": 0.33,
        "sentence_lines": False,
        "context_before": 1,
        "context_after": 3,
        "mirror": False,
        "animation": True,
        "show_cues": True,
        "highlight": True,
    },
    "voice": {"enabled": True, "wake_word": ""},
    "sounds": {"enabled": True, "volume": 0.5},
    "controls": {
        "pedal_device": "",
        "pedal_grab": False,
        "pedal_map": {
            "KEY_PAGEDOWN": "next",
            "KEY_PAGEUP": "back",
            "KEY_DOT": "toggle_pause",
            "KEY_B": "toggle_pause",
            "KEY_F5": "again",
            "KEY_ESC": "again",
        },
    },
    "edit": {
        "keep": "last",
        "handle_before": 0.08,
        "handle_after": 0.15,
        "max_pause": 0.7,
        "crossfade_ms": 15,
        "camera_crossfade_ms": 0,
    },
    # The Export dialogs' choices, remembered for the next export and for Ctrl+E.
    "export": {
        "video_format": "mp4-h264",
        "video_size": 0,
        "video_fps": 0,
        "video_quality": "high",
        "video_audio_bitrate": "192k",
        "burn_captions": False,
        "audio_format": "flac",
        "audio_bitrate": "192k",
        "audio_rate": 0,
        "audio_channels": 0,
        "audio_depth": 24,
        "loudness": 0.0,
        "chapters": True,
        "captions_format": "srt",
        "caption_line": 42,
        "caption_lines": 2,
        "timeline_format": "otio",
    },
    "layouts": {"custom": {}},
}

PRESETS = {
    "nvidia": {"device": "cuda", "vad": "silero", "tracking": "whisper", "scorer": "wav2vec2", "tts": "piper"},
    "amd": {"device": "cuda", "vad": "silero", "tracking": "vosk", "scorer": "wav2vec2", "tts": "piper"},
    "cpu": {"device": "cpu", "vad": "energy", "tracking": "vosk", "scorer": "wav2vec2", "tts": "espeak"},
    "light": {"device": "cpu", "vad": "energy", "tracking": "vosk", "scorer": "miscue", "tts": "espeak"},
}


def _merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def config_path() -> Path:
    return paths.config_dir() / "config.toml"


def load(path: Path | None = None) -> dict:
    path = path or config_path()
    if path.exists():
        try:
            return _merge(DEFAULTS, tomllib.loads(path.read_text(encoding="utf-8")))
        except tomllib.TOMLDecodeError:
            pass
    return copy.deepcopy(DEFAULTS)


def save(config: dict, path: Path | None = None) -> None:
    atomic_write(path or config_path(), tomli_w.dumps(config))


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def gpu_present() -> bool:
    return Path("/dev/nvidia0").exists() or Path("/dev/kfd").exists()


def whisper_cuda_ready() -> bool:
    """Whether CTranslate2 can find cuBLAS and cuDNN: the pip nvidia-* packages beside a wheel, or the
    system's CUDA libraries for a CTranslate2 built against them (Arch's ctranslate2-cuda)."""
    if os.environ.get("CUDA_VISIBLE_DEVICES") == "" or not Path("/dev/nvidia0").exists():
        return False
    from ctypes.util import find_library

    pip = importlib.util.find_spec("nvidia") is not None and all(
        importlib.util.find_spec(f"nvidia.{library}") is not None for library in ("cublas", "cudnn")
    )
    return pip or all(find_library(library) for library in ("cublas", "cudnn"))


def torch_device() -> str:
    spec = importlib.util.find_spec("torch")
    if spec is None or not spec.origin:
        return "none"
    version = Path(spec.origin).parent / "version.py"
    try:
        text = version.read_text()
    except OSError:
        return "cpu"
    accelerated = re.search(r"^(cuda|hip)\s*(?::[^=]*)?=\s*['\"]\d", text, re.MULTILINE)
    return "cuda" if accelerated and gpu_present() else "cpu"


def resolve_engines(config: dict, check_gpu: bool = True) -> dict:
    from .engine import models, tts, whisper_engine

    engines = dict(config["engines"])
    preset = engines.get("preset", "auto")
    if preset in PRESETS:
        engines.update({k: v for k, v in PRESETS[preset].items() if engines.get(k, "auto") == "auto" or k == "device"})
    torch_ok = has_module("torch")
    device = engines.get("device", "auto")
    if device == "auto":
        device = torch_device() if check_gpu and torch_ok else "cpu"
        if device == "none":
            device = "cpu"
    resolved = {"device": device, "threads": int(engines.get("threads", 4))}
    vad = engines.get("vad", "auto")
    if vad == "auto":
        vad = "silero" if torch_ok and models.get("silero-vad-5").installed() else "energy"
    resolved["vad"] = vad
    # Whisper runs on ctranslate2, whose CUDA build only needs the pip cuBLAS and cuDNN libraries,
    # so it can use the GPU even when the installed torch is the CPU build.
    whisper_gpu = device == "cuda" or (engines.get("device", "auto") == "auto" and check_gpu and whisper_cuda_ready())
    resolved["whisper_device"] = "cuda" if whisper_gpu else "cpu"
    tracking = engines.get("tracking", "auto")
    if tracking == "auto":
        tracking = "whisper" if whisper_gpu and whisper_engine.available() else "vosk"
    if tracking == "whisper" and not whisper_engine.available():
        tracking = "vosk"
    resolved["tracking"] = tracking
    resolved["whisper_model"] = engines.get("whisper_model", "small.en")
    scorer = engines.get("scorer", "auto")
    if scorer in ("auto", "wav2vec2"):
        scorer = "wav2vec2" if torch_ok and models.get("wav2vec2-espeak-cv").installed() else "miscue"
    resolved["scorer"] = scorer
    voice = engines.get("tts", "auto")
    if voice in ("auto", "piper"):
        voice = "piper" if tts.piper_binary() and models.get("piper-en-us-ljspeech-medium").installed() else "espeak"
    resolved["tts"] = voice
    resolved["commands"] = bool(engines.get("commands", True)) and config["voice"].get("enabled", True)
    return resolved
