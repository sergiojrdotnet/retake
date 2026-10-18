from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from . import exports, media
from .edl import Edit
from .render import audio_job, render_with_fallback, video_job

KINDS = ("video", "audio", "captions", "timeline", "sentences", "labels", "raw")


def probes(sources, probe: Callable = media.probe) -> dict:
    found = {}
    for source in sources:
        for path in (source.audio, source.video):
            if path is not None and path.exists():
                try:
                    found[path] = probe(path)
                except Exception:
                    pass
    return found


def export(kind: str, item, log, edit: Edit, settings: dict, script=None, probe: Callable = media.probe,
           progress: Callable[[float], None] = lambda fraction: None) -> Path:
    """Writes one kind of export into the item's out folder, with the choices in settings (config
    [export], which the Export dialogs remember)."""
    out = item.out_dir
    out.mkdir(parents=True, exist_ok=True)
    name = f"{item.project.title} · {item.title}"
    sources = item.sources()
    if kind in ("video", "audio"):
        extra = {"chapters": exports.chapters(log, edit, script) if settings.get("chapters") else [], "title": name, "progress": progress}
        if kind == "video":
            captions = exports.edited_words(log, edit) if settings.get("burn_captions") else []
            return render_with_fallback(video_job(edit, sources, out, settings, captions=captions, **extra))
        return render_with_fallback(audio_job(edit, sources, out, settings, **extra))
    if kind == "captions":
        filename, text = exports.captions_file(exports.edited_words(log, edit), settings)
    elif kind == "timeline":
        filename, text = exports.timeline_file(log, edit, sources, probes(sources, probe), settings, name, script)
    elif kind == "raw":
        exports.write(out / "labels.txt", exports.audacity_labels(log))
        filename, text = "raw.otio", exports.otio(log, None, sources, probes(sources, probe), name=name)
    elif kind == "labels":
        filename, text = "labels.txt", exports.audacity_labels(log)
    elif kind == "sentences":
        if script is None:
            raise ValueError("this recording has no script")
        filename, text = "sentences.json", json.dumps(exports.script_timing(script, log, edit, item.id), indent=1, ensure_ascii=False)
    else:
        raise ValueError(f"unknown export: {kind}")
    return exports.write(out / filename, text)
