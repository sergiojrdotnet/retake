from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class Monitor:
    name: str
    x: int
    y: int
    width: int
    height: int
    scale: float
    description: str = ""
    focused: bool = False

    @property
    def logical(self) -> tuple[int, int]:
        return int(self.width / self.scale), int(self.height / self.scale)


def available() -> bool:
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) and shutil.which("hyprctl") is not None


def _json(*args: str):
    output = subprocess.run(["hyprctl", "-j", *args], capture_output=True, text=True, timeout=5).stdout
    return json.loads(output or "null")


def monitors() -> list[Monitor]:
    if not available():
        return []
    result = []
    for m in _json("monitors") or []:
        transform = m.get("transform", 0)
        width, height = (m["height"], m["width"]) if transform in (1, 3, 5, 7) else (m["width"], m["height"])
        result.append(Monitor(m["name"], m["x"], m["y"], width, height, m.get("scale", 1.0), m.get("description", ""), m.get("focused", False)))
    return result


def monitor(name: str) -> Monitor | None:
    return next((m for m in monitors() if m.name == name), None)


def clients() -> list[dict]:
    if not available():
        return []
    return _json("clients") or []


def find_window(title: str) -> dict | None:
    return next((c for c in clients() if c.get("title") == title), None)


def dispatch(lua: str, classic: list[str]) -> bool:
    if not available():
        return False
    result = subprocess.run(["hyprctl", "dispatch", lua], capture_output=True, text=True, timeout=5)
    if result.returncode == 0 and not result.stdout.lower().startswith("error"):
        return True
    result = subprocess.run(["hyprctl", "dispatch", *classic], capture_output=True, text=True, timeout=5)
    return result.returncode == 0 and not result.stdout.lower().startswith("error")


def camera_geometry(target: Monitor, layout: str, aspect: float = 16 / 9) -> tuple[int, int, int, int]:
    width, height = target.logical
    if layout == "full":
        return target.x, target.y, width, height
    if layout == "small":
        box_width = int(width * 0.16)
    else:
        box_width = int(width * 0.24)
    box_height = int(box_width / aspect)
    margin = int(width * 0.02)
    return target.x + width - box_width - margin, target.y + height - box_height - margin, box_width, box_height


def place(title: str, geometry: tuple[int, int, int, int], pin: bool = True) -> bool:
    client = find_window(title)
    if client is None:
        return False
    window = f"address:{client['address']}"
    x, y, width, height = geometry
    if not client.get("floating"):
        dispatch(f'hl.dsp.window.float({{ window = "{window}", action = "toggle" }})', ["togglefloating", window])
    dispatch(f'hl.dsp.window.resize({{ window = "{window}", x = {width}, y = {height} }})', ["resizewindowpixel", f"exact {width} {height},{window}"])
    dispatch(f'hl.dsp.window.move({{ window = "{window}", x = {x}, y = {y} }})', ["movewindowpixel", f"exact {x} {y},{window}"])
    if pin and not client.get("pinned"):
        dispatch(f'hl.dsp.window.pin({{ window = "{window}" }})', ["pin", window])
    return True


def config_snippet() -> str:
    return "\n".join([
        "-- Retake: camera window floats, stays pinned and never steals focus",
        'o.window({ title = "^Retake camera$" }, { float = true, pin = true, no_initial_focus = true, no_dim = true, border_size = 0 })',
        "-- Retake: hide the prompter from screen sharing / portal capture",
        'o.window({ class = "^retake$", title = "^Retake$" }, { no_screen_share = true })',
        "",
        "-- Retake: control it while the recorded app has focus",
        'o.bind("SUPER + ALT + RIGHT", "Retake: next sentence", "retake ctl next")',
        'o.bind("SUPER + ALT + LEFT", "Retake: previous sentence", "retake ctl back")',
        'o.bind("SUPER + ALT + R", "Retake: retake", "retake ctl again")',
        'o.bind("SUPER + ALT + SPACE", "Retake: pause or resume", "retake ctl toggle-pause")',
        'o.bind("SUPER + ALT + M", "Retake: mark", "retake ctl mark")',
    ])
