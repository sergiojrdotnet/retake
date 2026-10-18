from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import __version__


def _check(args) -> int:
    from . import config as config_module
    from .languages import packs
    from .phonetics.guides import GuideBuilder
    from .script.lexicon import Lexicon
    from .script.parser import parse_file
    from .session import preflight

    config = config_module.load()
    pack = packs.get(args.language or config["general"]["script_language"])
    native = packs.get(args.native or config["general"]["native_language"])
    path = Path(args.script)
    script = parse_file(path, pack)
    guides = GuideBuilder(pack, native, Lexicon.for_script(path)).build(script)
    spoken = sum(1 for s in script.sentences if s.trackable)
    words = len(script.words)
    print(f"{script.title}: {len(script.sections)} sections, {spoken} sentences, {words} words, about {words / 140:.1f} min at 140 wpm")
    wake = config["voice"].get("wake_word") or pack.wake_word
    issues = preflight.check(script, guides, pack, wake)
    for issue in issues:
        print(f"  {issue.severity:7} {issue.message}")
    if args.guides:
        print()
        for key, guide in guides.by_key.items():
            if guide.syllables >= 3 or guide.oov or guide.heteronym:
                print(f"  {key:20} {guide.ipa:22} {guide.respell:22} {guide.native}")
    return 1 if any(i.severity == "error" for i in issues) else 0


def _guide(args) -> int:
    from . import config as config_module
    from .languages import packs
    from .phonetics.guides import GuideBuilder

    config = config_module.load()
    builder = GuideBuilder(packs.get(config["general"]["script_language"]), packs.get(args.native or config["general"]["native_language"]))
    for word in args.words:
        guide = builder.guide_for_text(word)
        print(f"{word:16} {guide.ipa:20} {guide.respell:20} {guide.native}")
    return 0


def _models(args) -> int:
    from .engine import models

    if args.action == "list":
        for spec in models.REGISTRY.values():
            state = "installed" if spec.installed() else "-"
            print(f"  {spec.id:30} {state:10} {spec.size_mb:6} MB  {spec.license:24} {spec.title}")
        return 0
    spec = models.get(args.id)
    if args.action == "remove":
        models.remove(spec.id)
        return 0

    def progress(done: int, total: int) -> None:
        if total:
            print(f"\r  {spec.id}: {done / total:5.1%}", end="", flush=True)

    models.Download(spec, progress).run()
    print(f"\n  installed {spec.id}")
    return 0


def _doctor(args) -> int:
    from . import config as config_module
    from .engine import models, settings, tts, whisper_engine
    from .video import phone

    config = config_module.load()
    checks = [
        ("espeak-ng", shutil.which("espeak-ng") is not None, "pronunciation guides and reference voice"),
        ("ffmpeg", shutil.which("ffmpeg") is not None, "rendering and exports"),
        ("scrcpy", phone.available(), "Android phone as camera (optional)"),
        ("vosk", config_module.has_module("vosk"), "voice following and commands"),
        ("torch", config_module.has_module("torch"), "Silero VAD and pronunciation scoring (optional)"),
        ("faster-whisper", whisper_engine.available(), "Whisper voice following (optional)"),
        ("piper", tts.piper_binary() is not None, "natural reference voice (optional)"),
        ("nvidia-ml-py", config_module.has_module("pynvml"), "NVIDIA resource monitor (optional)"),
        ("evdev", config_module.has_module("evdev"), "foot pedal grab (optional)"),
        ("jeepney", config_module.has_module("jeepney"), "file chooser portal"),
    ]
    for name, ok, purpose in checks:
        print(f"  {'✓' if ok else '✗'} {name:20} {purpose}")
    print("\n  models:")
    for spec in models.REGISTRY.values():
        if spec.installed():
            print(f"    ✓ {spec.id}")
    missing = settings.missing_models(config)
    for model in missing:
        print(f"    ✗ {model} (needed) → retake models pull {model}")
    resolved = config_module.resolve_engines(config, check_gpu=not args.no_gpu)
    print("\n  engines:", ", ".join(f"{k}={v}" for k, v in resolved.items()))
    return 1 if missing else 0


def _pick_item(args):
    from .project import Project

    project = Project.load(Path(args.project))
    items = [i for i in project.items if i.parts]
    if args.item:
        item = project.item(args.item)
        if item is None:
            raise SystemExit(f"no item {args.item!r}; items: {', '.join(i.id for i in project.items)}")
        return project, item
    if len(items) != 1:
        raise SystemExit(f"pick one with --item: {', '.join(i.id for i in items) or 'nothing recorded yet'}")
    return project, items[0]


def _render(args) -> int:
    from . import config as config_module
    from .edit.autoedit import Rules, auto_edit
    from .edit.outputs import KINDS, export

    _, item = _pick_item(args)
    log = item.load_takes()
    duration = item.duration
    config = config_module.load()
    rules = Rules.from_config(config["edit"], config["strictness"])
    edit = None if args.auto else item.load_edit()
    if edit is None:
        edit = auto_edit(log, duration, rules, item.boundaries())
        item.save_edit(edit)
    script = item.load_script()
    for target in args.targets.split(","):
        if target not in KINDS:
            print(f"  unknown target {target}; choose from {', '.join(KINDS)}")
            continue
        if target == "video" and not item.has_video:
            print("  no video in this item; skipping video")
            continue
        if target == "sentences" and script is None:
            print("  no script in this item; skipping sentences")
            continue
        export(target, item, log, edit, config["export"], script)
        print(f"  {target}: done")
    return 0


def _projects(args) -> int:
    import json

    from . import config as config_module
    from .project import Project, items_for_source, list_projects

    general = config_module.load()["general"]
    base = Path(args.dir or general["projects_dir"]).expanduser()
    recent = [] if args.dir else general.get("recent_projects", [])
    if args.script:
        rows = []
        for project, item in items_for_source(base, Path(args.script), recent):
            timing = item.out_dir / "sentences.json"
            rows.append({
                "project": str(project.path), "item": item.id, "folder": str(item.folder), "title": item.title,
                "parts": len(item.parts), "duration": item.duration, "sentences": str(timing) if timing.exists() else None,
            })
    else:
        rows = list_projects(base, recent)
        if args.items:
            for row in rows:
                project = Project.load(Path(row["path"]))
                row["items"] = [{"id": i.id, "kind": i.kind, "title": i.title, "folder": str(i.folder), "parts": len(i.parts)} for i in project.items]
    if args.json:
        print(json.dumps(rows, indent=1))
    else:
        for row in rows:
            print("  ".join(str(row.get(k, "")) for k in (("project", "item", "duration") if args.script else ("path", "scripts", "recordings"))))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    commands = {"ctl", "check", "guide", "models", "doctor", "render", "projects"}
    if not argv or argv[0] not in commands:
        parser = argparse.ArgumentParser(prog="retake", description="Solo talking recordings with the retakes handled for you.")
        parser.add_argument("path", nargs="?", help="a .retake project (or its folder) to open")
        parser.add_argument("--version", action="version", version=f"retake {__version__}")
        args = parser.parse_args(argv)
        from .ui.app import run

        return run(path=args.path)
    command, rest = argv[0], argv[1:]
    if command == "ctl":
        from .control import ctl

        return ctl.main(rest)
    parser = argparse.ArgumentParser(prog=f"retake {command}")
    if command == "check":
        parser.add_argument("script")
        parser.add_argument("--language")
        parser.add_argument("--native")
        parser.add_argument("--guides", action="store_true", help="list pronunciation guides for hard words")
        return _check(parser.parse_args(rest))
    if command == "guide":
        parser.add_argument("words", nargs="+")
        parser.add_argument("--native")
        return _guide(parser.parse_args(rest))
    if command == "models":
        parser.add_argument("action", choices=["list", "pull", "remove"], nargs="?", default="list")
        parser.add_argument("id", nargs="?")
        return _models(parser.parse_args(rest))
    if command == "doctor":
        parser.add_argument("--no-gpu", action="store_true", help="don't probe the GPU")
        return _doctor(parser.parse_args(rest))
    if command == "projects":
        parser.add_argument("script", nargs="?", help="only items imported from this script")
        parser.add_argument("--dir", help="projects folder (default: from settings)")
        parser.add_argument("--items", action="store_true", help="list each project's scripts and recordings")
        parser.add_argument("--json", action="store_true")
        return _projects(parser.parse_args(rest))
    if command == "render":
        parser.add_argument("project", help="a .retake file or project folder")
        parser.add_argument("--item", help="which script or recording, by id (see retake projects --items)")
        parser.add_argument("--auto", action="store_true", help="rebuild the edit with Auto edit first")
        parser.add_argument("--targets", default="audio,timeline,captions,sentences",
                            help="video, audio, captions, timeline, sentences, labels, raw; formats are the ones last chosen in the Export dialogs")
        return _render(parser.parse_args(rest))
    return 1


if __name__ == "__main__":
    sys.exit(main())
