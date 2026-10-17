from __future__ import annotations

import threading
import time
from typing import Callable

import numpy as np


class Player:
    def __init__(self):
        self.lock = threading.Lock()
        self.playing = False

    def play(self, audio: np.ndarray, rate: int, on_start: Callable[[], None] | None = None, on_end: Callable[[], None] | None = None) -> None:
        threading.Thread(target=self._run, args=(audio, rate, on_start, on_end), daemon=True).start()

    def _run(self, audio: np.ndarray, rate: int, on_start, on_end) -> None:
        import sounddevice as sd

        with self.lock:
            self.playing = True
            try:
                if on_start:
                    on_start()
                sd.play(audio.astype(np.float32), rate, blocking=False)
                time.sleep(len(audio) / rate + 0.05)
                sd.stop()
            except Exception:
                pass
            finally:
                self.playing = False
                if on_end:
                    on_end()
