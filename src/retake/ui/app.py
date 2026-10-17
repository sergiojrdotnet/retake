from __future__ import annotations

import os
import signal
import sys
from importlib import resources
from pathlib import Path

from .. import config as config_module
from .. import paths


def _translation_code(config: dict) -> str | None:
    wanted = config["general"].get("ui_language", "auto")
    if wanted in ("", "auto"):
        from PySide6.QtCore import QLocale

        wanted = QLocale.system().name().replace("_", "-")
    if wanted.lower().startswith("pt"):
        return "pt_BR"
    return None


def _desktop_entry_installed() -> bool:
    homes = [os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")]
    homes += (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    return any((Path(home) / "applications" / "retake.desktop").exists() for home in homes if home)


def _quiet_ffmpeg() -> None:
    # Qt Multimedia leaves FFmpeg's own logging on, which floods the terminal with muxer and
    # encoder-probe warnings; real failures still reach the window through Qt's error signals.
    # The level is set on the libavutil Qt already loaded: loading one by name could pull in a
    # second, different FFmpeg build next to Qt's.
    import ctypes

    from PySide6.QtMultimedia import QMediaDevices

    QMediaDevices.audioInputs()
    try:
        with open("/proc/self/maps", encoding="utf-8") as maps:
            loaded = next((line.split()[-1] for line in maps if "/libavutil.so" in line), None)
    except OSError:
        return
    if loaded:
        try:
            ctypes.CDLL(loaded).av_log_set_level(16)
        except (OSError, AttributeError):
            pass


def run(path: str | None = None, free: bool = False) -> int:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Material")
    from PySide6.QtCore import QLoggingCategory, QTimer, QTranslator
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
    from PySide6.QtQuickControls2 import QQuickStyle

    from .controller import Controller
    from .theme import Theme
    from .waveform import WaveformItem

    # Qt registers the app ID with the desktop portal while the application is created;
    # naming it afterwards makes Qt try a second time and the portal refuses.
    if not _desktop_entry_installed():
        # Running from a checkout: the portal can't find retake.desktop and Qt says so on every start.
        QLoggingCategory.setFilterRules("qt.qpa.services.warning=false")
    QGuiApplication.setApplicationName("Retake")
    QGuiApplication.setOrganizationName("retake")
    QGuiApplication.setDesktopFileName("retake")
    app = QGuiApplication(sys.argv[:1])
    # Qt Quick moves only 8 px per wheel "line" (24 px a notch at the default 3); 12 lines gives about
    # what Chromium and GTK apps scroll. Touchpads send exact pixel distances and aren't affected.
    app.styleHints().setWheelScrollLines(12)
    _quiet_ffmpeg()
    icon = resources.files("retake").joinpath("assets/retake.svg")
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    QQuickStyle.setStyle("Material")
    config = config_module.load()
    code = _translation_code(config)
    translator = QTranslator(app)
    if code:
        qm = resources.files("retake").joinpath(f"i18n/retake_{code}.qm")
        if qm.is_file() and translator.load(str(qm)):
            app.installTranslator(translator)
    qmlRegisterType(WaveformItem, "Retake", 1, 0, "Waveform")
    theme = Theme(paths.omarchy_theme_dir())
    controller = Controller()
    engine = QQmlApplicationEngine()
    context = engine.rootContext()
    context.setContextProperty("app", controller)
    context.setContextProperty("theme", theme)
    context.setContextProperty("editor", controller.editor)
    qml = Path(str(resources.files("retake").joinpath("qml/Main.qml")))
    engine.load(str(qml))
    if not engine.rootObjects():
        controller.shutdown()
        return 1
    controller.attach_window(engine.rootObjects()[0])
    if free:
        controller.startFree()
    elif path:
        target = Path(path).expanduser()
        if target.is_dir() or target.suffix == ".retake":
            controller.openProject(str(target))
        else:
            controller.openScript(str(target))
    app.aboutToQuit.connect(controller.shutdown)

    def stop(*_):
        controller.shutdown()
        app.quit()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    wake = QTimer(interval=500)
    wake.timeout.connect(lambda: None)
    wake.start()
    result = app.exec()
    del engine
    return result
