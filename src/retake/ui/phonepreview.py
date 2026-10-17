from __future__ import annotations

import subprocess
import threading
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QVideoFrame, QVideoSink

from ..edit import media
from ..video.phone import loopback_fed

LONG, SHORT = 640, 360


class PhonePreview(QObject):
    """Shows the phone's virtual camera in the camera panels.

    Qt's camera can't open a v4l2loopback device: it advertises every size up to 8192x8192 and Qt
    picks one the producer isn't writing. FFmpeg reads whatever scrcpy writes, scaled down for the panel."""

    _frame = Signal(int, QImage)
    activeChanged = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.sinks: list[QVideoSink] = []
        self.active = False
        self._process: subprocess.Popen | None = None
        self._generation = 0
        self._frame.connect(self._show)

    def add_sink(self, sink: QVideoSink) -> None:
        if sink not in self.sinks:
            self.sinks.append(sink)

    def start(self, device: str, portrait: bool = False) -> None:
        """(Re)starts reading; called each time scrcpy begins feeding the device."""
        self.stop()
        self._generation += 1
        size = (SHORT, LONG) if portrait else (LONG, SHORT)
        threading.Thread(target=self._read, args=(device, self._generation, *size), daemon=True).start()

    def stop(self) -> None:
        self._generation += 1
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.kill()
        self._set_active(False)

    def _read(self, device: str, generation: int, width: int, height: int) -> None:
        size = width * height * 4
        command = [
            media.ffmpeg(), "-v", "quiet", "-fflags", "nobuffer", "-f", "v4l2", "-i", device,
            # v4l2loopback hands the latest frame out again as fast as it's read; 30 fps is plenty for a panel.
            "-vf", f"fps=30,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "-pix_fmt", "rgba", "-f", "rawvideo", "-",
        ]
        deadline = time.monotonic() + 20
        while generation == self._generation and time.monotonic() < deadline:
            if not loopback_fed(device):
                time.sleep(0.1)
                continue
            try:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            except OSError:
                return
            self._process = process
            frames = 0
            while generation == self._generation:
                data = process.stdout.read(size)
                if len(data) < size:
                    break
                frames += 1
                self._frame.emit(generation, QImage(data, width, height, width * 4, QImage.Format.Format_RGBA8888).copy())
            if process.poll() is None:
                process.kill()
            if frames:
                return
            time.sleep(0.25)

    def _show(self, generation: int, image: QImage) -> None:
        if generation != self._generation:
            return
        frame = QVideoFrame(image)
        for sink in self.sinks:
            sink.setVideoFrame(frame)
        self._set_active(True)

    def _set_active(self, active: bool) -> None:
        if self.active != active:
            self.active = active
            self.activeChanged.emit()
