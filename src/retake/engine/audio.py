from __future__ import annotations

import bisect
import threading

import numpy as np

RATE = 16000


class AudioHistory:
    def __init__(self, seconds: float = 900.0):
        self.capacity = int(seconds * RATE)
        self.buffer = np.zeros(self.capacity, dtype=np.int16)
        self.end = 0
        self.lock = threading.Lock()

    def reset(self) -> None:
        with self.lock:
            self.end = 0

    def append(self, start_sample: int, samples: np.ndarray) -> None:
        with self.lock:
            if start_sample > self.end:
                gap = min(start_sample - self.end, self.capacity)
                self._write(self.end, np.zeros(gap, dtype=np.int16))
            elif start_sample < self.end:
                samples = samples[self.end - start_sample:]
                start_sample = self.end
            self._write(start_sample, samples)

    def _write(self, start: int, samples: np.ndarray) -> None:
        n = len(samples)
        if n == 0:
            return
        if n > self.capacity:
            samples = samples[-self.capacity:]
            start += n - self.capacity
            n = self.capacity
        offset = start % self.capacity
        first = min(n, self.capacity - offset)
        self.buffer[offset:offset + first] = samples[:first]
        if first < n:
            self.buffer[: n - first] = samples[first:]
        self.end = start + n

    def slice(self, start_time: float, end_time: float) -> np.ndarray:
        with self.lock:
            start = max(int(start_time * RATE), self.end - self.capacity, 0)
            end = min(int(end_time * RATE), self.end)
            if end <= start:
                return np.zeros(0, dtype=np.int16)
            indices = np.arange(start, end) % self.capacity
            return self.buffer[indices].copy()

    @property
    def duration(self) -> float:
        return self.end / RATE


class SpeechTimeline:
    def __init__(self):
        self.lock = threading.Lock()
        self.segments: list[list[float]] = []

    def reset(self) -> None:
        with self.lock:
            self.segments.clear()

    def speech_started(self, time: float) -> None:
        with self.lock:
            self.segments.append([time, float("inf")])

    def speech_ended(self, time: float) -> None:
        with self.lock:
            if self.segments and self.segments[-1][1] == float("inf"):
                self.segments[-1][1] = time

    def speaking(self) -> bool:
        with self.lock:
            return bool(self.segments) and self.segments[-1][1] == float("inf")

    def speech_between(self, start: float, end: float) -> float:
        with self.lock:
            total = 0.0
            starts = [s[0] for s in self.segments]
            index = max(0, bisect.bisect_right(starts, start) - 1)
            for a, b in self.segments[index:]:
                if a >= end:
                    break
                total += max(0.0, min(b, end) - max(a, start))
            return total

    def last_end_before(self, time: float) -> float | None:
        with self.lock:
            ends = [b for a, b in self.segments if b <= time]
            return ends[-1] if ends else None
