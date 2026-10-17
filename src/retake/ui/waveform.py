from __future__ import annotations

import numpy as np
from PySide6.QtCore import Property, QLineF, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtQuick import QQuickPaintedItem

_shared_peaks: dict[str, np.ndarray] = {}


def publish_peaks(key: str, peaks: np.ndarray) -> None:
    _shared_peaks[key] = peaks


class WaveformItem(QQuickPaintedItem):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._key = ""
        self._per_second = 100
        self._start = 0.0
        self._end = 10.0
        self._color = QColor("#888888")
        self._kept_color = QColor("#FFD60A")
        self._kept: list = []
        self.setAntialiasing(False)

    def _setter(name: str):
        def setter(self, value):
            if getattr(self, name) != value:
                setattr(self, name, value)
                self.changed.emit()
                self.update()
        return setter

    key = Property(str, lambda self: self._key, _setter("_key"), notify=changed)
    perSecond = Property(int, lambda self: self._per_second, _setter("_per_second"), notify=changed)
    viewStart = Property(float, lambda self: self._start, _setter("_start"), notify=changed)
    viewEnd = Property(float, lambda self: self._end, _setter("_end"), notify=changed)
    color = Property(QColor, lambda self: self._color, _setter("_color"), notify=changed)
    keptColor = Property(QColor, lambda self: self._kept_color, _setter("_kept_color"), notify=changed)
    kept = Property("QVariantList", lambda self: self._kept, _setter("_kept"), notify=changed)

    def paint(self, painter: QPainter) -> None:
        peaks = _shared_peaks.get(self._key)
        width, height = int(self.width()), self.height()
        if peaks is None or width <= 0 or self._end <= self._start:
            return
        span = self._end - self._start
        middle = height / 2
        kept = [(float(k["start"]), float(k["end"])) for k in self._kept] if self._kept else []
        dim = QPen(self._color)
        bright = QPen(self._kept_color)
        lines_dim, lines_bright = [], []
        for x in range(width):
            t0 = self._start + span * x / width
            t1 = self._start + span * (x + 1) / width
            a = max(0, int(t0 * self._per_second))
            b = min(len(peaks), max(a + 1, int(t1 * self._per_second)))
            if a >= len(peaks):
                break
            value = float(peaks[a:b].max()) if b > a else 0.0
            half = max(0.5, min(1.0, value ** 0.6) * middle * 0.95)
            line = QLineF(x + 0.5, middle - half, x + 0.5, middle + half)
            center = (t0 + t1) / 2
            if any(s <= center < e for s, e in kept):
                lines_bright.append(line)
            else:
                lines_dim.append(line)
        painter.setPen(dim)
        painter.drawLines(lines_dim)
        painter.setPen(bright)
        painter.drawLines(lines_bright)
