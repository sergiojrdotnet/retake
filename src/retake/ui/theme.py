from __future__ import annotations

import tomllib
from importlib import resources
from pathlib import Path

from PySide6.QtCore import Property, QFileSystemWatcher, QObject, QUrl, Signal

from .. import paths

DEFAULTS = {
    "accent": "#FFD60A",
    "background": "#121212",
    "foreground": "#E8E8E8",
    "muted": "#8A8A8A",
    "red": "#E5484D",
    "green": "#46A758",
    "yellow": "#F5D90A",
    "lighter_background": "#1E1E1E",
}


def _color(name: str, signal: Signal) -> Property:
    return Property(str, lambda self: self.colors.get(name, DEFAULTS.get(name, "#ffffff")), notify=signal)


class Theme(QObject):
    changed = Signal()

    def __init__(self, directory: Path, parent=None):
        super().__init__(parent)
        self.directory = directory
        self.colors = dict(DEFAULTS)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._reload)
        self.watcher.directoryChanged.connect(self._reload)
        self._reload()

    def _reload(self, *_):
        colors = dict(DEFAULTS)
        file = self.directory / "colors.toml"
        try:
            data = tomllib.loads(file.read_text(encoding="utf-8"))
            colors.update({k: v for k, v in data.items() if isinstance(v, str) and v.startswith("#")})
        except (OSError, tomllib.TOMLDecodeError):
            pass
        self.colors = colors
        self._logo = self._write_logo(colors["accent"])
        watched = self.watcher.files() + self.watcher.directories()
        if watched:
            self.watcher.removePaths(watched)
        for path in (file, self.directory, self.directory.parent):
            if path.exists():
                self.watcher.addPath(str(path))
        self.changed.emit()

    @staticmethod
    def _write_logo(color: str) -> str:
        template = resources.files("retake").joinpath("assets/retake-symbolic.svg").read_text(encoding="utf-8")
        target = paths.cache_dir() / f"logo-{color.lstrip('#').lower()}.svg"
        if not target.exists():
            target.write_text(template.replace("currentColor", color), encoding="utf-8")
        return QUrl.fromLocalFile(str(target)).toString()

    logo = Property(str, lambda self: self._logo, notify=changed)
    accent = _color("accent", changed)
    background = _color("background", changed)
    foreground = _color("foreground", changed)
    muted = _color("muted", changed)
    red = _color("red", changed)
    green = _color("green", changed)
    yellow = _color("yellow", changed)
    surface = _color("lighter_background", changed)
