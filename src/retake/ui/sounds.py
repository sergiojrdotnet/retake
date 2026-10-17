from __future__ import annotations

import numpy as np
import soundfile as sf
from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QMediaDevices, QSoundEffect

from .. import paths

RATE = 48000
VERSION = 1

CUES: dict[str, tuple[list[tuple[float, float]], float]] = {
    "start": ([(660, 0.09), (990, 0.14)], 0.0),
    "pause": ([(990, 0.09), (660, 0.14)], 0.0),
    "stop": ([(990, 0.08), (784, 0.08), (587, 0.2)], 0.0),
    "retake": ([(392, 0.13), (0, 0.06), (392, 0.13)], 0.35),
    "command": ([(1320, 0.05)], 0.0),
    "end": ([(523, 0.1), (659, 0.1), (784, 0.24)], 0.0),
    "pass": ([(1175, 0.07)], 0.0),
    "miss": ([(294, 0.16)], 0.35),
}


def cue_for_state(previous: str, state: str) -> str | None:
    if state == "listening" and previous != "listening":
        return "start"
    if state == "paused" and previous == "listening":
        return "pause"
    if state == "stopped" and previous != "stopped":
        return "stop"
    return None


def cue_for_notice(kind: str, text: str) -> str | None:
    if kind in ("retake", "end"):
        return kind
    if kind == "pickups-done":
        return "end"
    if kind == "drill-pass":
        return "pass"
    if kind == "drill-miss":
        return "miss"
    if kind == "command" and text not in ("pause", "resume", "stop"):
        return "command"
    return None


def synthesize(notes: list[tuple[float, float]], harmonic: float = 0.0) -> np.ndarray:
    parts = []
    for frequency, seconds in notes:
        t = np.arange(int(RATE * seconds)) / RATE
        if frequency <= 0:
            parts.append(np.zeros_like(t))
            continue
        tone = np.sin(2 * np.pi * frequency * t) + harmonic * np.sin(4 * np.pi * frequency * t)
        attack = np.minimum(1.0, t / 0.005)
        decay = np.exp(-t / (seconds * 0.45))
        parts.append(tone * attack * decay / (1 + harmonic))
    signal = np.concatenate(parts + [np.zeros(int(RATE * 0.02))])
    return (signal * 0.6).astype(np.float32)


class SoundCues(QObject):
    def __init__(self, config: dict, parent: QObject | None = None):
        super().__init__(parent)
        self.config = config
        self._effects: dict[str, QSoundEffect] = {}
        # Loaded up front: a cue that has to be read from disk first plays late, and the retake cue
        # has to sound the moment a word misses.
        for name in CUES:
            self._load(name)

    def play(self, name: str | None) -> None:
        settings = self.config.get("sounds", {})
        if not settings.get("enabled", True) or name not in CUES:
            return
        effect = self._effects.get(name) or self._load(name)
        # An effect keeps the device it was created on; follow the default (a headset plugged in later).
        default = QMediaDevices.defaultAudioOutput()
        if effect.audioDevice() != default:
            effect.setAudioDevice(default)
        effect.setVolume(float(settings.get("volume", 0.5)))
        effect.play()

    def _load(self, name: str) -> QSoundEffect:
        notes, harmonic = CUES[name]
        path = paths.cache_dir() / "sounds" / f"{name}-v{VERSION}.wav"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(path, synthesize(notes, harmonic), RATE, subtype="PCM_16")
        effect = QSoundEffect(self)
        effect.setSource(QUrl.fromLocalFile(str(path)))
        self._effects[name] = effect
        return effect
