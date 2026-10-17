from __future__ import annotations

import io
import shutil
import subprocess
from functools import lru_cache

import numpy as np
import soundfile


class EspeakMissing(RuntimeError):
    pass


def binary() -> str:
    path = shutil.which("espeak-ng")
    if not path:
        raise EspeakMissing("espeak-ng is not installed")
    return path


def available() -> bool:
    return shutil.which("espeak-ng") is not None


def ipa_batch(words: list[str], voice: str) -> list[str]:
    if not words:
        return []
    result = subprocess.run(
        [binary(), "-q", "--ipa=3", "-v", voice],
        input="\n".join(words) + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(lines) == len(words):
        return lines
    return [ipa(word, voice) for word in words]


@lru_cache(maxsize=4096)
def ipa(text: str, voice: str) -> str:
    result = subprocess.run(
        [binary(), "-q", "--ipa=3", "-v", voice, text],
        capture_output=True,
        text=True,
        check=True,
    )
    return " ".join(line.strip() for line in result.stdout.splitlines() if line.strip())


def synthesize(text: str, voice: str, words_per_minute: int = 150) -> tuple[np.ndarray, int]:
    result = subprocess.run(
        [binary(), "-v", voice, "-s", str(words_per_minute), "--stdout", text],
        capture_output=True,
        check=True,
    )
    audio, rate = soundfile.read(io.BytesIO(result.stdout), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio, rate
