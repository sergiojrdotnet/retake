from __future__ import annotations

import json
import threading
from pathlib import Path

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from .. import config as config_module
from .. import paths
from ..edit import exports, media
from ..edit.autoedit import Rules, auto_edit, flag_screen_changes
from ..edit.edl import Edit, History
from ..edit.render import RenderJob, render_with_fallback
from ..project import Item
from ..session.takes import COMPLETE, TakeLog
from .waveform import publish_peaks

RENDER_TARGETS = {
    "video": "video.mp4",
    "video-hevc": "video-hevc.mp4",
    "narration-flac": "narration.flac",
    "narration-wav": "narration.wav",
    "narration-opus": "narration.opus",
    "narration-mp3": "narration.mp3",
}


class EditorController(QObject):
    loadedChanged = Signal()
    editChanged = Signal()
    mediaChanged = Signal()
    renderChanged = Signal()
    message = Signal(str, str)
    _peaksReady = Signal(str)
    _thumbsReady = Signal("QVariant")
    _renderDone = Signal(str, str)
    _renderProgress = Signal(float)
    _changesReady = Signal("QVariant")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.item: Item | None = None
        self.directory: Path | None = None
        self.log: TakeLog | None = None
        self.history: History | None = None
        self.script = None
        self.duration = 0.0
        self.part_list: list = []
        self._peaks_key = ""
        self._thumbs: list = []
        self._dirty = False
        self._rendering = False
        self._render_progress = 0.0
        self._screen_flags: list = []
        self._peaksReady.connect(self._on_peaks)
        self._thumbsReady.connect(self._on_thumbs)
        self._renderDone.connect(self._on_render_done)
        self._renderProgress.connect(self._on_render_progress)
        self._changesReady.connect(self._on_changes)

    @property
    def edit(self) -> Edit | None:
        return self.history.edit if self.history else None

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def has_video(self) -> bool:
        return any(part.video is not None for part in self.part_list)

    def load(self, item: Item) -> None:
        self.item = item
        self.directory = item.folder
        self.log = item.load_takes()
        self.script = item.load_script()
        self.part_list = item.parts
        self.duration = item.duration
        edit = Edit.load(item.edit_path) if item.edit_path.exists() else None
        if edit is None:
            edit = self._auto()
        edit.source_duration = self.duration
        if self._multipart():
            edit.order = "script"
        self.history = History(edit)
        self._dirty = False
        self._thumbs = []
        self._screen_flags = []
        self.loadedChanged.emit()
        self.editChanged.emit()
        self.mediaChanged.emit()
        threading.Thread(target=self._compute_peaks, args=(item.folder, list(self.part_list), self.duration), daemon=True).start()
        if self.has_video:
            threading.Thread(target=self._compute_thumbs, args=(item, list(self.part_list)), daemon=True).start()

    def unload(self) -> None:
        self.item = None
        self.directory = None
        self.log = None
        self.history = None
        self.part_list = []
        self.loadedChanged.emit()
        self.editChanged.emit()
        self.mediaChanged.emit()

    def _multipart(self) -> bool:
        return len(self.part_list) > 1 and self.item is not None and self.item.kind == "script"

    def rules(self) -> Rules:
        config = config_module.load()
        rules = Rules.from_config(config["edit"], config["strictness"])
        if self._multipart():
            # Recordings and pickups made on different days only line up in script order.
            rules.order = "script"
        return rules

    def _auto(self) -> Edit:
        return auto_edit(self.log, self.duration, self.rules(), self.item.boundaries() if self.item else [])

    def _compute_peaks(self, folder: Path, parts: list, duration: float) -> None:
        import numpy as np

        chunks = []
        try:
            for part in parts:
                expected = int(round(part.duration * 100))
                values = media.peaks(part.audio, 100, paths.cache_dir() / "peaks") if part.audio.exists() else np.zeros(expected, dtype=np.float32)
                values = np.asarray(values, dtype=np.float32)[:expected]
                if len(values) < expected:
                    values = np.concatenate([values, np.zeros(expected - len(values), dtype=np.float32)])
                chunks.append(values)
        except Exception as error:
            self.message.emit("error", f"Waveform failed: {error}")
            return
        key = f"{folder}#{len(parts)}"
        publish_peaks(key, np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32))
        self._peaksReady.emit(key)

    def _on_peaks(self, key: str) -> None:
        self._peaks_key = key
        self.mediaChanged.emit()

    def _compute_thumbs(self, item: Item, parts: list) -> None:
        thumbs = []
        try:
            every = max(1.0, sum(p.duration for p in parts) / 400)
            for part in parts:
                if part.video is None:
                    continue
                stat = part.video.stat()
                # Keyed to the file itself: trimming or repairing a video must not reuse old thumbnails.
                directory = paths.cache_dir() / "thumbs" / f"{item.project.directory.name}-{item.id}-{part.index}-{stat.st_size}-{int(stat.st_mtime)}"
                files = media.thumbnails(part.video, directory, every)
                for i, f in enumerate(files):
                    local = self._audio_time(part, i * every)
                    if local is not None and 0 <= local < part.duration:
                        thumbs.append({"time": part.start + local, "url": QUrl.fromLocalFile(str(f)).toString()})
            self._thumbsReady.emit(thumbs)
        except Exception as error:
            self.message.emit("error", f"Thumbnails failed: {error}")

    @staticmethod
    def _audio_time(part, video_time: float) -> float | None:
        """The moment of the part's audio a video frame belongs to; None for footage that was cut."""
        if not part.video_segments:
            return video_time + part.video_offset
        for segment in part.video_segments:
            local = video_time + segment.offset
            if segment.audio_start - 0.5 <= local <= segment.audio_end + 0.5:
                return local
        return None

    def _on_thumbs(self, thumbs) -> None:
        self._thumbs = thumbs
        self.mediaChanged.emit()

    def _changed(self) -> None:
        self._dirty = True
        self.editChanged.emit()

    def _checkpoint(self) -> None:
        if self.history:
            self.history.checkpoint()

    @Slot()
    def autoEdit(self) -> None:
        if self.log is None:
            return
        self._checkpoint()
        self.history.edit = self._auto()
        self._changed()
        self.message.emit("info", f"Auto edit: kept {len(self.edit.clips)} clips, {self.edit.duration:.1f} s of {self.duration:.1f} s recorded")
        if self.has_video:
            threading.Thread(target=self._detect_screen_changes, daemon=True).start()

    def _detect_screen_changes(self) -> None:
        edit = self.edit
        clips = sorted(edit.clips, key=lambda c: c.start)
        changes = []
        for part in self.part_list:
            if part.video is None:
                continue
            from ..edit.trim import offset_at

            def video_time(t: float) -> float:
                local = t - part.start
                return local - offset_at(list(part.video_segments), part.video_offset, local)

            gaps = [(video_time(a.end), video_time(b.start)) for a, b in zip(clips, clips[1:]) if b.start - a.end > 1.0 and part.start <= a.end and b.start <= part.end]
            try:
                changes += [part.start + self._audio_time(part, t) for t in media.screen_changes(part.video, gaps) if self._audio_time(part, t) is not None]
            except Exception:
                continue
        self._changesReady.emit([{"start": a, "end": b} for a, b in flag_screen_changes(edit, changes)])

    def _on_changes(self, flags) -> None:
        self._screen_flags = flags
        if flags:
            self.message.emit("info", f"{len(flags)} cut(s) skip screen activity; check them before rendering")
        self.editChanged.emit()

    def apply_recording(self, sentences: set[int]) -> list[int]:
        """After a new part: swap in its takes for these sentences, keeping every other edit."""
        from ..edit.autoedit import update_sentences

        if self.edit is None:
            return []
        self._checkpoint()
        updated = update_sentences(self.edit, self.log, sentences, self.rules(), self.duration, self.item.boundaries())
        if self._multipart():
            self.edit.order = "script"
        self._changed()
        return updated

    @Slot()
    def undo(self) -> None:
        if self.history and self.history.undo():
            self._changed()

    @Slot()
    def redo(self) -> None:
        if self.history and self.history.redo():
            self._changed()

    @Slot()
    def save(self) -> None:
        if self.item and self.edit:
            self.edit.save(self.item.edit_path)
            self.log.save()
            self._dirty = False
            self.editChanged.emit()
            self.message.emit("info", "Edit saved")

    @Slot(float)
    def split(self, t: float) -> None:
        self._checkpoint()
        if self.edit.split(t):
            self._changed()

    @Slot(float)
    def removeAt(self, t: float) -> None:
        clip = self.edit.clip_at(t)
        self._checkpoint()
        if clip is not None:
            self.edit.remove(clip.id)
        else:
            gap = self.edit.gap_at(t)
            if gap is None:
                return
            take = next((k for k in self.log.takes if k.start <= t < (k.end or k.start)), None)
            start, end = gap
            if take is not None:
                start, end = max(start, take.start - 0.08), min(end, (take.end or end) + 0.15)
            self.edit.restore(start, end, take=take.id if take else None, sentence=take.sentence if take else None)
        self._changed()

    @Slot(str, float)
    def setEdge(self, edge: str, t: float) -> None:
        clip = self.edit.clip_at(t) or self._nearest_clip(t)
        if clip is None:
            return
        self._checkpoint()
        if self.edit.set_edge(clip.id, edge, t):
            self._changed()

    def _nearest_clip(self, t: float):
        clips = self.edit.clips
        return min(clips, key=lambda c: min(abs(c.start - t), abs(c.end - t))) if clips else None

    @Slot(float)
    def cycleTake(self, t: float) -> None:
        take = next((k for k in self.log.takes if k.start <= t < (k.end or k.start)), None)
        clip = self.edit.clip_at(t)
        sentence = take.sentence if take else (clip.sentence if clip else None)
        if sentence is None:
            self.message.emit("info", "No script sentence here")
            return
        options = [k for k in self.log.takes if k.sentence == sentence and k.status == COMPLETE]
        if len(options) < 2:
            self.message.emit("info", "Only one good take for this sentence")
            return
        current = next((c.take for c in self.edit.clips if c.sentence == sentence), None)
        ids = [k.id for k in options]
        index = (ids.index(current) + 1) % len(ids) if current in ids else 0
        chosen = options[index]
        for k in options:
            k.preferred = k.id == chosen.id
        self._checkpoint()
        rules = self.rules()
        self.edit.replace_take(sentence, chosen.start - rules.handle_before, (chosen.end or chosen.start) + rules.handle_after, chosen.id)
        self._changed()
        self.message.emit("info", f"Sentence {sentence + 1}: take {chosen.number}")

    @Slot(float, int, result=float)
    def nextEdge(self, t: float, direction: int) -> float:
        points = set(self.edit.edges())
        for take in self.log.takes:
            points.add(round(take.start, 3))
        for marker in self.log.markers:
            points.add(round(marker.start, 3))
        ordered = sorted(points)
        if direction > 0:
            return next((p for p in ordered if p > t + 0.02), self.duration)
        return next((p for p in reversed(ordered) if p < t - 0.02), 0.0)

    @Slot(float, result=float)
    def playableFrom(self, t: float) -> float:
        clip = self.edit.clip_at(t)
        if clip is not None:
            return t
        following = [c.start for c in self.edit.clips if c.start > t]
        return min(following) if following else -1.0

    def _clip_row(self, clip) -> dict:
        return {"id": clip.id, "start": clip.start, "end": clip.end, "sentence": -1 if clip.sentence is None else clip.sentence}

    @Slot(float, result="QVariant")
    def clipAt(self, t: float):
        clip = self.edit.clip_at(t) if self.edit else None
        return self._clip_row(clip) if clip else None

    @Slot(int, result="QVariant")
    def nextClip(self, clip_id: int):
        """The clip that plays after this one, in edit order (script order can jump back in time)."""
        timeline = self.edit.timeline() if self.edit else []
        ids = [c.id for c in timeline]
        if clip_id not in ids:
            return self._clip_row(timeline[0]) if timeline else None
        position = ids.index(clip_id) + 1
        return self._clip_row(timeline[position]) if position < len(timeline) else None

    @Slot(result="QVariant")
    def firstClip(self):
        timeline = self.edit.timeline() if self.edit else []
        return self._clip_row(timeline[0]) if timeline else None

    @Slot(float, result=int)
    def sentenceAt(self, t: float) -> int:
        clip = self.edit.clip_at(t) if self.edit else None
        if clip is not None and clip.sentence is not None:
            return clip.sentence
        take = next((k for k in self.log.takes if k.start <= t < (k.end or k.start) and k.sentence is not None), None) if self.log else None
        return take.sentence if take else -1

    @Slot(str)
    def render(self, target: str) -> None:
        if self._rendering or self.edit is None:
            return
        out = self.item.out_dir
        out.mkdir(parents=True, exist_ok=True)
        name = f"{self.item.project.title} · {self.item.title}"
        sources = self.item.sources()
        try:
            if target == "timeline":
                path = exports.write(out / "timeline.otio", exports.otio(self.log, self.edit, sources, self._video_durations(), name=name))
                self._on_render_done(str(path), "")
                return
            if target == "raw":
                path = exports.write(out / "raw.otio", exports.otio(self.log, None, sources, self._video_durations(), name=name))
                exports.write(out / "labels.txt", exports.audacity_labels(self.log))
                self._on_render_done(str(path), "")
                return
            if target == "captions":
                words = exports.edited_words(self.log, self.edit)
                exports.write(out / "captions.vtt", exports.webvtt(words))
                path = exports.write(out / "captions.srt", exports.srt(words))
                self._on_render_done(str(path), "")
                return
            if target == "labels":
                path = exports.write(out / "labels.txt", exports.audacity_labels(self.log))
                self._on_render_done(str(path), "")
                return
            if target == "sentences":
                if self.script is None:
                    raise ValueError("this recording has no script")
                timing = exports.script_timing(self.script, self.log, self.edit, self.item.id)
                path = exports.write(out / "sentences.json", json.dumps(timing, indent=1, ensure_ascii=False))
                self._on_render_done(str(path), "")
                return
        except Exception as error:
            self._on_render_done("", str(error))
            return
        if target not in RENDER_TARGETS:
            return
        with_video = target.startswith("video")
        if with_video and not self.has_video:
            self.message.emit("error", "This recording has no video; render a narration instead")
            return
        config = config_module.load()["edit"]
        job = RenderJob(
            edit=self.edit,
            sources=sources,
            output=out / RENDER_TARGETS[target],
            with_video=with_video,
            encoder="hevc" if target == "video-hevc" else "auto",
            normalize=bool(config.get("normalize")),
            loudness=float(config.get("loudness", -16.0)),
            chapters=exports.chapters(self.log, self.edit),
            title=name,
            progress=self._renderProgress.emit,
        )
        self._rendering = True
        self._render_progress = 0.0
        self.renderChanged.emit()
        threading.Thread(target=self._render_job, args=(job,), daemon=True).start()

    def _video_durations(self) -> dict:
        durations = {}
        for part in self.part_list:
            if part.video is not None:
                try:
                    durations[part.video] = media.probe(part.video).duration
                except Exception:
                    pass
        return durations

    def _render_job(self, job: RenderJob) -> None:
        try:
            path = render_with_fallback(job)
            self._renderDone.emit(str(path), "")
        except Exception as error:
            self._renderDone.emit("", str(error))

    def _on_render_progress(self, fraction: float) -> None:
        self._render_progress = fraction
        self.renderChanged.emit()

    def _on_render_done(self, path: str, error: str) -> None:
        self._rendering = False
        self.renderChanged.emit()
        if error:
            self.message.emit("error", f"Export failed: {error}")
            return
        self.message.emit("info", f"Saved {Path(path).name}")
        self.save()

    @Slot()
    def openOutput(self) -> None:
        if self.item:
            folder = self.item.out_dir
            folder.mkdir(exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _clips(self) -> list[dict]:
        if self.edit is None:
            return []
        return [{"id": c.id, "start": c.start, "end": c.end, "take": c.take or -1, "sentence": -1 if c.sentence is None else c.sentence, "kind": c.kind, "label": c.label} for c in self.edit.clips]

    def _segments(self) -> list[dict]:
        """The edit as it plays: the kept clips in play order, each with where it starts in the edit and
        the take it comes from."""
        if self.edit is None:
            return []
        takes = {t.id: t for t in self.log.takes} if self.log else {}
        rows = []
        position = 0.0
        for clip in self.edit.timeline():
            take = takes.get(clip.take)
            rows.append({
                "id": clip.id, "start": clip.start, "end": clip.end, "editStart": position,
                "sentence": -1 if clip.sentence is None else clip.sentence, "kind": clip.kind, "label": clip.label,
                "number": take.number if take else 0, "status": take.status if take else "complete", "chosen": True,
                "score": -1 if take is None or take.score is None else round(take.score),
                "flagged": len(take.flagged) if take else 0,
                "skipped": sum(1 for f in take.flagged if f.get("drill") == "skipped") if take else 0,
                "stale": bool(take and take.stale), "text": take.text if take else clip.label, "reason": take.reason if take else "",
            })
            position += clip.end - clip.start
        return rows

    def _takes(self) -> list[dict]:
        if self.log is None:
            return []
        chosen = {c.take for c in self.edit.clips} if self.edit else set()
        return [{
            "id": t.id, "sentence": -1 if t.sentence is None else t.sentence, "number": t.number, "status": t.status,
            "reason": t.reason, "start": t.start, "end": t.end or t.start, "score": -1 if t.score is None else round(t.score),
            "flagged": len(t.flagged), "skipped": sum(1 for f in t.flagged if f.get("drill") == "skipped"),
            "chosen": t.id in chosen, "text": t.text, "stale": t.stale,
        } for t in self.log.takes]

    def _stale_sentences(self) -> list[int]:
        """Sentences whose take in the edit was recorded against older wording of the script."""
        if self.edit is None or self.log is None:
            return []
        takes = {t.id: t for t in self.log.takes}
        return sorted({c.sentence for c in self.edit.clips if c.sentence is not None and c.take in takes and takes[c.take].stale})

    def _markers(self) -> list[dict]:
        if self.log is None:
            return []
        rows = [{"kind": m.kind, "start": m.start, "end": m.end, "label": m.label} for m in self.log.markers]
        for take in self.log.takes:
            for flagged in take.flagged:
                when = flagged.get("start") or take.start
                rows.append({"kind": "flag", "start": when, "end": flagged.get("end") or when, "label": flagged.get("text", "")})
        rows.extend({"kind": "screen", "start": f["start"], "end": f["end"], "label": "screen changed"} for f in self._screen_flags)
        return rows

    def _words(self) -> list[dict]:
        if self.log is None:
            return []
        return [{"start": w.start, "end": w.end, "text": w.text, "score": -1 if w.score is None else w.score} for t in self.log.takes for w in t.words]

    def _part_rows(self) -> list[dict]:
        rows = []
        for number, part in enumerate(self.part_list, start=1):
            rows.append({
                "index": part.index, "start": part.start, "end": part.end, "kind": part.kind,
                "audioUrl": QUrl.fromLocalFile(str(part.audio)).toString(),
                "videoUrl": QUrl.fromLocalFile(str(part.video)).toString() if part.video else "",
                "hasVideo": part.video is not None, "videoOffset": part.video_offset,
                "segments": [{"start": seg.audio_start, "end": seg.audio_end, "offset": seg.offset} for seg in part.video_segments],
                "label": ("Pickups" if part.kind == "pickup" else "Recording") + f" {number}",
            })
        return rows

    loaded = Property(bool, lambda self: self.log is not None, notify=loadedChanged)
    hasScript = Property(bool, lambda self: self.script is not None, notify=loadedChanged)
    title = Property(str, lambda self: f"{self.item.project.title} · {self.item.title}" if self.item else "", notify=loadedChanged)
    sourceDuration = Property(float, lambda self: self.duration, notify=loadedChanged)
    hasVideo = Property(bool, lambda self: self.has_video, notify=mediaChanged)
    parts = Property("QVariant", _part_rows, notify=mediaChanged)
    peaksKey = Property(str, lambda self: self._peaks_key, notify=mediaChanged)
    thumbnails = Property("QVariant", lambda self: self._thumbs, notify=mediaChanged)
    clips = Property("QVariant", _clips, notify=editChanged)
    takes = Property("QVariant", _takes, notify=editChanged)
    segments = Property("QVariant", _segments, notify=editChanged)
    markers = Property("QVariant", _markers, notify=editChanged)
    words = Property("QVariant", _words, notify=loadedChanged)
    editDuration = Property(float, lambda self: self.edit.duration if self.edit else 0.0, notify=editChanged)
    staleSentences = Property("QVariant", _stale_sentences, notify=editChanged)
    canUndo = Property(bool, lambda self: bool(self.history and self.history.undo_stack), notify=editChanged)
    canRedo = Property(bool, lambda self: bool(self.history and self.history.redo_stack), notify=editChanged)
    isDirty = Property(bool, lambda self: self._dirty, notify=editChanged)
    rendering = Property(bool, lambda self: self._rendering, notify=renderChanged)
    renderProgress = Property(float, lambda self: self._render_progress, notify=renderChanged)
