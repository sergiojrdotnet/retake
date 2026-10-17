from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .audio import RATE

FRAME = 512
ONSET_FRAMES = 3
HANGOVER = 0.3


class _Hysteresis:
    def __init__(self):
        self.speaking = False
        self.run = 0
        self.silence_since: float | None = None

    def step(self, active: bool, time: float, events: list[tuple[bool, float]]) -> None:
        if active:
            self.silence_since = None
            self.run += 1
            if not self.speaking and self.run >= ONSET_FRAMES:
                self.speaking = True
                events.append((True, time - (ONSET_FRAMES - 1) * FRAME / RATE))
        else:
            self.run = 0
            if self.speaking:
                if self.silence_since is None:
                    self.silence_since = time
                elif time - self.silence_since >= HANGOVER:
                    self.speaking = False
                    events.append((False, self.silence_since))
                    self.silence_since = None


class EnergyVad:
    name = "energy"

    def __init__(self, margin_db: float = 11.0):
        self.margin = margin_db
        self.floor = -60.0
        self.state = _Hysteresis()
        self.pending = np.zeros(0, dtype=np.int16)
        self.position = 0

    def reset(self, start_sample: int = 0) -> None:
        self.state = _Hysteresis()
        self.pending = np.zeros(0, dtype=np.int16)
        self.position = start_sample

    def process(self, start_sample: int, samples: np.ndarray) -> list[tuple[bool, float]]:
        if not len(self.pending):
            self.position = start_sample
        self.pending = np.concatenate([self.pending, samples])
        events: list[tuple[bool, float]] = []
        while len(self.pending) >= FRAME:
            frame = self.pending[:FRAME].astype(np.float32) / 32768.0
            self.pending = self.pending[FRAME:]
            level = 10 * math.log10(float(np.mean(frame * frame)) + 1e-10)
            if level < self.floor:
                self.floor = level
            else:
                self.floor += (level - self.floor) * (0.002 if level > self.floor + self.margin else 0.02)
            active = level > max(self.floor + self.margin, -50.0)
            self.position += FRAME
            self.state.step(active, self.position / RATE, events)
        return events


class SileroVad:
    name = "silero"

    def __init__(self, model_path: Path, threshold: float = 0.5, device: str = "cpu"):
        import torch

        self.torch = torch
        torch.set_num_threads(max(1, min(2, torch.get_num_threads())))
        self.model = torch.jit.load(str(model_path), map_location=device)
        self.model.eval()
        self.threshold = threshold
        self.state = _Hysteresis()
        self.pending = np.zeros(0, dtype=np.int16)
        self.position = 0

    def reset(self, start_sample: int = 0) -> None:
        self.model.reset_states()
        self.state = _Hysteresis()
        self.pending = np.zeros(0, dtype=np.int16)
        self.position = start_sample

    def process(self, start_sample: int, samples: np.ndarray) -> list[tuple[bool, float]]:
        if not len(self.pending):
            self.position = start_sample
        self.pending = np.concatenate([self.pending, samples])
        events: list[tuple[bool, float]] = []
        with self.torch.inference_mode():
            while len(self.pending) >= FRAME:
                frame = self.torch.from_numpy(self.pending[:FRAME].astype(np.float32) / 32768.0)
                self.pending = self.pending[FRAME:]
                probability = float(self.model(frame, RATE).item())
                self.position += FRAME
                self.state.step(probability >= self.threshold, self.position / RATE, events)
        return events
