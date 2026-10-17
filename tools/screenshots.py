"""Render README screenshots offscreen from a demo script and a synthetic recording.

    .venv/bin/python tools/screenshots.py [--out docs/screenshots] [--lang pt_BR]

Uses CPU only, never opens the camera and never records the microphone into a session.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = """# Event Store Study Case

## Introduction

(SCENE: Camera) Hi, I'm Sergio. / Today we **aggregate** the event store snapshots and measure P99 latency.

(SMILE) We flush the cache to disk // and compare the throughput with the 2026 benchmark.

## Results

(CAMERA: corner) The asynchronous writer kept every request under ten milliseconds.
"""


def build_project(base: Path, script: Path):
    import numpy as np
    import soundfile
    import soxr

    from retake.phonetics import espeak
    from retake.project import Project
    from retake.session import takes as kinds
    from retake.session.takes import COMPLETE, REJECTED, TakeLog, WordTiming

    project = Project.create(base / "Event Store Course", "Event Store Course")
    item = project.add_script(script, "Episode 1 · Introduction")
    second = script.with_name("ep2.md")
    second.write_text("# Episode 2 · Results\n\nThe asynchronous writer kept every request under ten milliseconds.\n")
    project.add_script(second, "Episode 2 · Results")
    (item.folder / "video").mkdir(parents=True, exist_ok=True)
    item.snapshot_file.write_text(script.read_text())
    log = TakeLog(item.takes_path)
    parts, clock = [], 0.0

    def add(text, sentence, status, reason=""):
        nonlocal clock
        audio, rate = espeak.synthesize(text, "en-us", 155)
        audio = soxr.resample(audio, rate, 48000).astype(np.float32)
        start = clock + 0.8
        parts.extend([np.zeros(int(48000 * 0.8), dtype=np.float32), audio])
        clock = start + len(audio) / 48000
        if sentence is None:
            return start, clock
        take = log.new_take(sentence, start - 0.1, text)
        take.end, take.status, take.reason = clock + 0.1, status, reason
        words = text.split()
        step = (clock - start) / len(words)
        take.words = [WordTiming(i, w, start + i * step, start + (i + 0.9) * step) for i, w in enumerate(words)]
        take.score = 74.0 if status == COMPLETE else None
        return start, clock

    add("Hi, I'm Sergio.", 0, COMPLETE)
    add("Today we aggregate the event store", 1, REJECTED, "restart")
    add("Today we aggregate the event store snapshots and measure P99 latency.", 1, COMPLETE)
    start, end = add("retake again", None, None)
    log.add_marker(kinds.COMMAND, start, end, "again")
    add("We flush the cache to disk and compare the throughput with the 2026 benchmark.", 2, COMPLETE)
    log.add_marker(kinds.CHAPTER, 0.7, 0.7, "Introduction")
    log.takes[2].flagged = [{"text": "aggregate", "score": 41, "start": log.takes[2].start + 0.6, "end": log.takes[2].start + 1.1}]
    parts.append(np.zeros(48000, dtype=np.float32))
    audio = item.folder / "part-001.flac"
    soundfile.write(audio, np.concatenate(parts), 48000, subtype="PCM_24")
    log.save()
    duration = sum(len(p) for p in parts) / 48000
    video = item.folder / "video" / "part-001.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={duration}",
         "-i", str(audio), "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(video)],
        check=True,
    )
    item.add_part(1, audio, duration, video=video, video_method="timestamp")
    return project, item


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "docs/screenshots"))
    parser.add_argument("--lang", default="")
    parser.add_argument("--size", default="1400x860")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="retake-shots-"))
    os.environ.update({
        "QT_QPA_PLATFORM": "offscreen", "CUDA_VISIBLE_DEVICES": "", "RETAKE_NO_CAMERA": "1",
        "XDG_CONFIG_HOME": str(scratch / "config"),
    })
    sys.path.insert(0, str(ROOT / "src"))
    script = scratch / "event-store.md"
    script.write_text(SCRIPT)
    (scratch / "config/retake").mkdir(parents=True)
    project, item = build_project(scratch / "projects", script)
    (scratch / "config/retake/config.toml").write_text(
        f"[general]\nprojects_dir = \"{scratch / 'projects'}\"\nrecent_projects = [\"{project.path}\"]\n"
        "[prompter]\nanimation = false\n[guides]\nipa = true\n[video]\nbackend = \"builtin\"\n"
    )

    from importlib import resources

    from PySide6.QtCore import QObject, QTimer, QTranslator
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
    from PySide6.QtQuickControls2 import QQuickStyle

    from retake import paths
    from retake.ui.controller import Controller
    from retake.ui.theme import Theme
    from retake.ui.waveform import WaveformItem

    app = QGuiApplication(sys.argv[:1])
    app.setDesktopFileName("retake")
    QQuickStyle.setStyle("Material")
    if args.lang:
        translator = QTranslator(app)
        if translator.load(str(resources.files("retake").joinpath(f"i18n/retake_{args.lang}.qm"))):
            app.installTranslator(translator)
    qmlRegisterType(WaveformItem, "Retake", 1, 0, "Waveform")
    theme = Theme(paths.omarchy_theme_dir())
    controller = Controller()
    engine = QQmlApplicationEngine()
    context = engine.rootContext()
    context.setContextProperty("app", controller)
    context.setContextProperty("theme", theme)
    context.setContextProperty("editor", controller.editor)
    engine.load(str(resources.files("retake").joinpath("qml/Main.qml")))
    window = engine.rootObjects()[0]
    width, height = (int(v) for v in args.size.split("x"))
    window.resize(width, height)

    class Take:
        id, sentence, text, score = 2, 1, "Today we aggregate the event store snapshots", 52

    flagged = [{
        "text": "aggregate", "score": 41, "expected": "ˈæɡɹɪɡət", "heard": "ˈæɡɹɪɡeɪt", "word": 5,
        "patterns": [{"id": "vowel-length", "title": "Long vs short i", "description": "English separates long /iː/ (beach) from short /ɪ/ (bitch)."}],
    }]
    steps = [
        (1500, lambda: shot("start")),
        (100, lambda: controller.openProject(str(project.path))),
        (1200, lambda: controller.position_changed(1, 4)),
        (900, lambda: shot("prompter")),
        (100, lambda: window.setProperty("helpVisible", True)),
        (700, lambda: shot("help")),
        (100, lambda: (window.setProperty("helpVisible", False), window.findChild(QObject, "modelsDialog").open())),
        (900, lambda: shot("models")),
        (100, lambda: window.findChild(QObject, "modelsDialog").close()),
        (100, lambda: (controller.setLayout(2), controller.coach_feedback(Take(), flagged, []))),
        (900, lambda: shot("coach")),
        (100, lambda: controller.setLayout(4)),
        (1200, lambda: shot("studio")),
        (100, lambda: (controller.setLayout(1), controller.setSetting("prompter", "mode", "card"))),
        (900, lambda: shot("card")),
        (100, lambda: (controller.setSetting("prompter", "mode", "scroll"), controller.openItem(item.id, "studio"))),
        (3500, lambda: controller.editor.autoEdit()),
        (1200, lambda: shot("editor")),
        (300, lambda: (controller.editor.save(), controller.shutdown(), app.quit())),
    ]

    def shot(name: str) -> None:
        window.grabWindow().save(str(out / f"{name}.png"))
        print("saved", out / f"{name}.png", flush=True)

    def run(index: int = 0) -> None:
        if index >= len(steps):
            return
        delay, action = steps[index]

        def fire() -> None:
            action()
            run(index + 1)

        QTimer.singleShot(delay, fire)

    run()
    result = app.exec()
    del engine
    return result


if __name__ == "__main__":
    sys.exit(main())
