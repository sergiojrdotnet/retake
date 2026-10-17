from __future__ import annotations

import threading
from typing import Callable


class Pedal:
    def __init__(self, path: str, mapping: dict[str, str], on_action: Callable[[str], None], grab: bool = True):
        self.path = path
        self.mapping = mapping
        self.on_action = on_action
        self.grab = grab
        self.device = None
        self.thread: threading.Thread | None = None
        self.running = False
        self.error = ""

    def start(self) -> bool:
        try:
            import evdev
        except ImportError:
            self.error = "python-evdev is not installed"
            return False
        try:
            self.device = evdev.InputDevice(self.path)
            if self.grab:
                self.device.grab()
        except PermissionError:
            self.error = "no permission to read the pedal: add your user to the 'input' group"
            return False
        except OSError as error:
            self.error = str(error)
            return False
        self.running = True
        self.thread = threading.Thread(target=self._loop, args=(evdev,), name="pedal", daemon=True)
        self.thread.start()
        return True

    def _loop(self, evdev) -> None:
        try:
            for event in self.device.read_loop():
                if not self.running:
                    break
                if event.type != evdev.ecodes.EV_KEY or event.value != 1:
                    continue
                name = evdev.ecodes.KEY.get(event.code)
                if isinstance(name, list):
                    name = name[0]
                action = self.mapping.get(name or "")
                if action:
                    self.on_action(action)
        except OSError as error:
            self.error = str(error)

    def stop(self) -> None:
        self.running = False
        if self.device is not None:
            try:
                if self.grab:
                    self.device.ungrab()
                self.device.close()
            except OSError:
                pass
