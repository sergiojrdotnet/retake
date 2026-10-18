from __future__ import annotations

import numpy as np

# Above the room's noise by this much, a moment holds speech (or a breath); below it, only the room.
QUIET_DB = 10.0


class Quiet:
    """Where a recording is silent, from its waveform peaks: cuts go in the pauses between words."""

    def __init__(self, peaks: np.ndarray, per_second: int = 100):
        levels = 20 * np.log10(np.maximum(peaks, 1e-6))
        recorded = levels[peaks > 0]
        floor = float(np.percentile(recorded, 10)) if len(recorded) else 0.0
        self.silent = levels < floor + QUIET_DB
        self.per_second = per_second

    def runs(self, start: float, end: float, shortest: float) -> list[tuple[float, float]]:
        """The silences at least `shortest` long between start and end, cut to that span."""
        first = max(0, int(round(start * self.per_second)))
        last = min(len(self.silent), int(round(end * self.per_second)))
        if last <= first:
            return []
        edges = np.diff(np.concatenate([[0], self.silent[first:last].astype(np.int8), [0]]))
        found = []
        for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
            if (b - a) / self.per_second >= shortest:
                found.append(((first + a) / self.per_second, (first + b) / self.per_second))
        return found
