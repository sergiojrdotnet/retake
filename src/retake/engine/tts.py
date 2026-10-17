from __future__ import annotations

import json
import shutil
import subprocess
from functools import cache
from pathlib import Path

import numpy as np

from ..phonetics import espeak


class EspeakVoice:
    name = "espeak-ng"

    def __init__(self, voice: str):
        self.voice = voice

    def synthesize(self, text: str, slow: bool = False, ipa: str | None = None) -> tuple[np.ndarray, int]:
        return espeak.synthesize(text, self.voice, 115 if slow else 160)


@cache
def piper_binary() -> str | None:
    # Arch's official "piper" package is a gaming-mouse configurator, so a plain "piper" on the
    # PATH only counts when its help text is Piper's text-to-speech CLI.
    path = shutil.which("piper-tts")
    if path:
        return path
    path = shutil.which("piper")
    if path is None:
        return None
    try:
        result = subprocess.run([path, "--help"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return path if "--model" in result.stdout + result.stderr else None


# The voice's phoneme set comes from espeak, which writes the stressed NURSE vowel as ɜː.
IPA_SPELLINGS = {"ɝ": "ɜː", "g": "ɡ", "'": "ˈ", "/": " "}


class PiperVoice:
    name = "piper"

    def __init__(self, model: Path, binary: str | None = None):
        self.binary = binary or piper_binary()
        if not self.binary:
            raise FileNotFoundError("piper is not installed")
        self.model = model
        self.config = json.loads(model.with_suffix(model.suffix + ".json").read_text())
        self.rate = int(self.config.get("audio", {}).get("sample_rate", 22050))
        self.symbols = set(self.config.get("phoneme_id_map", {}))
        self._phoneme_config: Path | None = None

    def phonemes(self, ipa: str) -> str:
        """IPA as this voice's phoneme input: the first reading, in its own symbols, nothing it can't say."""
        first = ipa.strip().strip("/[]").split("|")[0].split(",")[0]
        spelled = "".join(IPA_SPELLINGS.get(ch, ch) for ch in first)
        return "".join(ch for ch in spelled if ch in self.symbols).strip()

    def phoneme_config(self) -> Path:
        """A copy of the voice's config that reads its input as phonemes. Fed IPA, Piper then says exactly
        that pronunciation instead of espeak's reading of the spelling, which for a word like "live" or
        "inserts" may be the other sense."""
        if self._phoneme_config is None:
            from .. import paths

            path = paths.cache_dir() / "piper" / f"{self.model.name}.phonemes.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({**self.config, "phoneme_type": "text"}, ensure_ascii=False), encoding="utf-8")
            self._phoneme_config = path
        return self._phoneme_config

    def synthesize(self, text: str, slow: bool = False, ipa: str | None = None) -> tuple[np.ndarray, int]:
        command = [self.binary, "--model", str(self.model), "--output_raw"]
        phonemes = self.phonemes(ipa) if ipa else ""
        if phonemes:
            command += ["--config", str(self.phoneme_config())]
            text = phonemes
        if slow:
            command += ["--length_scale", "1.35"]
        result = subprocess.run(command, input=text.encode("utf-8"), capture_output=True, check=True)
        audio = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        return audio, self.rate
