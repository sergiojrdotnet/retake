from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from .. import config as config_module
from .. import paths
from ..edit import exports, media
from ..edit.autoedit import Rules, auto_edit, take_blocks, take_choices, use_take
from ..edit.edl import Edit, History
from ..edit.quiet import Quiet
from ..edit import outputs
from ..edit import render as render_module
from ..project import Item
from ..session import takes as kinds
from ..session.takes import TakeLog
from .waveform import publish_peaks

class EditorController(QObject):
    loadedChanged = Signal()
    editChanged = Signal()
    resetChanged = Signal()
    mediaChanged = Signal()
    renderChanged = Signal()
    message = Signal(str, str)
    _peaksReady = Signal(str)
    _thumbsReady = Signal("QVariant")
    _renderDone = Signal(str, str)
    _renderProgress = Signal(float)

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
        self._silences: Quiet | None = None
        self._thumbs: list = []
        self._dirty = False
        # Changes are written shortly after they're made, so a burst of trims is one write.
        self._autosave = QTimer(self, singleShot=True, interval=400)
        self._autosave.timeout.connect(self.save)
        self._rendering = False
        self._render_progress = 0.0
        self._probe_cache: dict = {}
        self._peaksReady.connect(self._on_peaks)
        self._thumbsReady.connect(self._on_thumbs)
        self._renderDone.connect(self._on_render_done)
        self._renderProgress.connect(self._on_render_progress)

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
        self._silences = None
        edit = item.load_edit()
        fresh = edit is None
        if fresh:
            edit = self._auto()
        edit.source_duration = self.duration
        self.history = History(edit)
        self._dirty = fresh and bool(self.part_list)
        if self._dirty:
            self.save()
        self._thumbs = []
        self.loadedChanged.emit()
        self.editChanged.emit()
        self.resetChanged.emit()
        self.mediaChanged.emit()
        threading.Thread(target=self._compute_peaks, args=(item.folder, list(self.part_list), self.duration), daemon=True).start()
        if self.has_video:
            threading.Thread(target=self._compute_thumbs, args=(item, list(self.part_list)), daemon=True).start()
            # Trying the GPU encoders takes a moment; done now, the Video export dialog opens without a stall.
            threading.Thread(target=lambda: [render_module.video_encoder(codec) for codec in render_module.VIDEO_ENCODERS], daemon=True).start()

    def unload(self) -> None:
        self.save()
        self.item = None
        self.directory = None
        self.log = None
        self.history = None
        self.part_list = []
        self._silences = None
        self.loadedChanged.emit()
        self.editChanged.emit()
        self.mediaChanged.emit()

    def rules(self) -> Rules:
        config = config_module.load()
        return Rules.from_config(config["edit"], config["strictness"])

    def _auto(self) -> Edit:
        return auto_edit(self.log, self.duration, self.rules(), self.item.boundaries() if self.item else [], self._quiet())

    def _quiet(self) -> Quiet | None:
        """The recording's silences, so cuts land between words; read from the waveform cache that
        finishing a recording fills."""
        if self._silences is None and self.part_list:
            try:
                self._silences = Quiet(media.joined_peaks(self.part_list, paths.cache_dir() / "peaks"))
            except Exception as error:
                self.message.emit("error", f"Couldn't read the recording's pauses ({error}); cuts follow the word times only")
        return self._silences

    def _compute_peaks(self, folder: Path, parts: list, duration: float) -> None:
        try:
            values = media.joined_peaks(parts, paths.cache_dir() / "peaks")
        except Exception as error:
            self.message.emit("error", f"Waveform failed: {error}")
            return
        key = f"{folder}#{len(parts)}"
        publish_peaks(key, values)
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
        self.resetChanged.emit()
        self._autosave.start()

    def _is_automatic(self) -> bool:
        """Whether the edit is what the takes and the current rules would give anyway: then a reset
        has nothing to do."""
        if self.edit is None or self.log is None or not self.part_list:
            return True

        def shape(edit: Edit) -> list:
            return [(round(c.start, 3), round(c.end, 3), c.take, c.kind) for c in sorted(edit.clips, key=lambda c: (c.start, c.id))]

        return shape(self._auto()) == shape(self.edit)

    def _checkpoint(self) -> None:
        if self.history:
            self.history.checkpoint()

    @Slot()
    def resetEdit(self) -> None:
        """Back to the automatic cut with the current rules; Ctrl+Z brings the hand edits back."""
        if self.log is None or self._is_automatic():
            return
        self._checkpoint()
        self.history.edit = self._auto()
        self._changed()
        self.message.emit("info", f"Edit reset: kept {len(self.edit.clips)} clips, {self.edit.duration:.1f} s of {self.duration:.1f} s recorded (Ctrl+Z undoes)")

    def apply_recording(self, sentences: set[int]) -> list[int]:
        """After a new part: swap in its takes for these sentences, keeping every other edit."""
        from ..edit.autoedit import update_sentences

        if self.edit is None:
            return []
        self._checkpoint()
        updated = update_sentences(self.edit, self.log, sentences, self.rules(), self.duration, self.item.boundaries(), self._quiet())
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
        self._autosave.stop()
        if self._dirty and self.item and self.edit:
            with self.item.project.store.batch():
                self.item.save_edit(self.edit)
                self.log.save()
            self._dirty = False

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

    @Slot(int, int)
    def cycleTake(self, sentence: int, direction: int) -> None:
        """T / Shift+T: the next (older) or previous take of the sentence, in the side panel's order."""
        if sentence < 0 or self.log is None:
            self.message.emit("info", "No script sentence here")
            return
        options = take_choices(self.log, sentence)
        if len(options) < 2:
            self.message.emit("info", "This sentence has only one take")
            return
        current = next((c.take for c in self.edit.clips if c.sentence == sentence), None)
        ids = [k.id for k in options]
        index = (ids.index(current) + direction) % len(ids) if current in ids else 0
        self.useTake(options[index].id)

    @Slot(int, result=float)
    def useTake(self, take_id: int) -> float:
        """Puts this take in its sentence's place; returns where it now starts (recording time)."""
        take = next((k for k in self.log.takes if k.id == take_id), None) if self.log else None
        if take is None or take.sentence is None or take.end is None:
            return -1.0
        self._checkpoint()
        if use_take(self.edit, self.log, take, self.rules(), self.duration, self.item.boundaries(), self._quiet()):
            self._changed()
            self.message.emit("info", f"Sentence {take.sentence + 1}: take {take.number}")
        return min((c.start for c in self.edit.clips if c.take == take.id), default=take.start)

    @Slot(int, result="QVariant")
    def sentenceChoices(self, sentence: int) -> dict:
        if self.log is None or sentence < 0:
            return {}
        in_use = {c.take for c in self.edit.clips if c.sentence == sentence} if self.edit else set()
        text = ""
        if self.script is not None and sentence < len(self.script.sentences):
            text = self.script.sentences[sentence].text
        return {
            "sentence": sentence,
            "text": text,
            "takes": [{**self._take_info(take), "inUse": take.id in in_use, "recorded": self._recorded_label(take)}
                      for take in take_choices(self.log, sentence)],
        }

    def _take_info(self, take) -> dict:
        return {
            "take": take.id, "number": take.number, "status": take.status, "duration": round(take.duration, 1),
            "score": -1 if take.score is None else round(take.score),
            "flagged": len(take.flagged),
            "skipped": sum(1 for f in take.flagged if f.get("drill") == "skipped"),
            "stale": bool(take.stale), "text": take.text, "reason": take.reason,
        }

    def _recorded_label(self, take) -> str:
        """Which recording a take is in and roughly when it was read, e.g. "Pickups 2 · 14:05"."""
        from datetime import datetime, timedelta

        rows = self._part_rows()
        part = next((p for p in self.part_list if p.start <= take.start < p.end), None)
        if part is None:
            return ""
        label = next((r["label"] for r in rows if r["index"] == part.index), "")
        try:
            finished = datetime.fromisoformat(part.created)
        except ValueError:
            return label
        read = (finished - timedelta(seconds=part.end - take.start)).astimezone()
        when = read.strftime("%H:%M") if read.date() == datetime.now().astimezone().date() else read.strftime("%b %d, %H:%M")
        return f"{label} · {when}" if label else when

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

    @Slot(result="QVariant")
    def markPoints(self) -> list[float]:
        """Where takes and markers start, on the recording's clock; the edit view keeps those it shows."""
        points = {round(take.start, 3) for take in self.log.takes} if self.log else set()
        points |= {round(marker.start, 3) for marker in self.log.markers} if self.log else set()
        return sorted(points)

    @Slot(float)
    def saveFrame(self, t: float) -> None:
        """Saves the video frame at this moment as a PNG in the script's out folder (thumbnails, slides)."""
        part = self.item.part_at(t) if self.item else None
        if part is None or part.video is None:
            self.message.emit("error", "There's no video at this moment")
            return
        from ..edit.trim import offset_at

        local = t - part.start
        video_time = local - offset_at(list(part.video_segments), part.video_offset, local)
        if video_time < 0:
            self.message.emit("error", "The video hadn't started yet at this moment")
            return
        minutes, seconds = divmod(t, 60)
        path = self.item.out_dir / f"frame-{int(minutes):02d}m{seconds:04.1f}s.png"

        def grab():
            path.parent.mkdir(parents=True, exist_ok=True)
            result = subprocess.run([media.ffmpeg(), "-v", "error", "-y", "-ss", f"{video_time:.3f}", "-i", str(part.video), "-frames:v", "1", str(path)],
                                    capture_output=True, text=True)
            if result.returncode == 0 and path.exists():
                self.message.emit("info", f"Frame saved: out/{path.name}")
            else:
                self.message.emit("error", f"Couldn't save the frame: {result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'ffmpeg failed'}")

        threading.Thread(target=grab, daemon=True).start()

    def _clip_row(self, clip) -> dict:
        return {"id": clip.id, "start": clip.start, "end": clip.end, "sentence": -1 if clip.sentence is None else clip.sentence}

    @Slot(float, result="QVariant")
    def clipAt(self, t: float):
        clip = self.edit.clip_at(t) if self.edit else None
        return self._clip_row(clip) if clip else None

    @Slot(float, result=int)
    def sentenceAt(self, t: float) -> int:
        clip = self.edit.clip_at(t) if self.edit else None
        if clip is not None and clip.sentence is not None:
            return clip.sentence
        take = next((k for k in self.log.takes if k.start <= t < (k.end or k.start) and k.sentence is not None), None) if self.log else None
        return take.sentence if take else -1

    @Slot(str)
    def render(self, kind: str) -> None:
        """Exports with the choices remembered from that kind's Export dialog."""
        if self._rendering or self.edit is None:
            return
        if kind == "video" and not self.has_video:
            self.message.emit("error", "This recording has no video; export the audio instead")
            return
        if kind == "sentences" and self.script is None:
            self.message.emit("error", "This recording has no script")
            return
        self._rendering = True
        self._render_progress = 0.0
        self.renderChanged.emit()
        edit = Edit.from_dict(self.edit.as_dict())
        threading.Thread(target=self._export, args=(kind, edit), daemon=True).start()

    def _export(self, kind: str, edit: Edit) -> None:
        try:
            self._renderDone.emit(str(self._write_export(kind, edit)), "")
        except Exception as error:
            self._renderDone.emit("", str(error))

    def _write_export(self, kind: str, edit: Edit) -> Path:
        return outputs.export(kind, self.item, self.log, edit, config_module.load()["export"], self.script, self._probe, self._renderProgress.emit)

    def _probe(self, path: Path):
        stamp = (path, path.stat().st_mtime)
        if stamp not in self._probe_cache:
            self._probe_cache[stamp] = media.probe(path)
        return self._probe_cache[stamp]

    @Slot(result="QVariant")
    def videoShape(self) -> dict:
        """The first recording's picture, so the Video export dialog never offers to upscale."""
        if self.item is None:
            return {}
        video = next((source.video for source in self.item.sources() if source.video is not None), None)
        if video is None:
            return {}
        try:
            info = self._probe(video)
        except Exception:
            return {}
        return {"width": info.width, "height": info.height, "fps": round(info.fps, 2)}

    @Slot(str, result=str)
    def videoEncoder(self, video_format: str) -> str:
        fmt = render_module.VIDEO_FORMATS.get(video_format)
        return render_module.video_encoder(fmt.codec) if fmt else ""

    @Slot(str, result=str)
    def exportName(self, kind: str) -> str:
        settings = config_module.load()["export"]
        if kind == "video":
            return render_module.video_output_name(settings)
        if kind == "audio":
            return render_module.audio_output_name(settings)
        if kind == "captions":
            return exports.CAPTION_FORMATS.get(settings["captions_format"], "")
        if kind == "timeline":
            return exports.TIMELINE_FORMATS.get(settings["timeline_format"], "")
        return ""

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

    def _blocks(self) -> list[dict]:
        """V on a scripted recording: each take in use shown whole, in the order the edit plays, so
        what was cut from it shows (greyed) and can be restored. Laid out back to back like segments."""
        if self.edit is None or self.log is None or self.item is None:
            return []
        rows = []
        position = 0.0
        for start, end, clips, take in take_blocks(self.edit, self.log, self.rules(), self.duration, self.item.boundaries()):
            first = clips[0]
            info = self._take_info(take) if take else {"take": -1, "number": 0, "status": "complete", "score": -1, "flagged": 0, "skipped": 0, "stale": False, "text": first.label, "reason": ""}
            rows.append({**info, "start": start, "end": end, "editStart": position, "sentence": -1 if first.sentence is None else first.sentence,
                         "kind": first.kind, "chosen": True})
            position += end - start
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
        # A script's chapters come from its sections (the chapters lane), not from the markers logged while recording.
        rows = [{"kind": m.kind, "start": m.start, "end": m.end, "label": m.label} for m in self.log.markers
                if not (self.script is not None and m.kind == kinds.CHAPTER)]
        for take in self.log.takes:
            for flagged in take.flagged:
                when = flagged.get("start") or take.start
                rows.append({"kind": "flag", "start": when, "end": flagged.get("end") or when, "label": flagged.get("text", "")})
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
    sourceDuration = Property(float, lambda self: self.duration, notify=loadedChanged)
    hasVideo = Property(bool, lambda self: self.has_video, notify=mediaChanged)
    parts = Property("QVariant", _part_rows, notify=mediaChanged)
    peaksKey = Property(str, lambda self: self._peaks_key, notify=mediaChanged)
    thumbnails = Property("QVariant", lambda self: self._thumbs, notify=mediaChanged)
    clips = Property("QVariant", _clips, notify=editChanged)
    takes = Property("QVariant", _takes, notify=editChanged)
    segments = Property("QVariant", _segments, notify=editChanged)
    blocks = Property("QVariant", _blocks, notify=editChanged)
    scriptSections = Property("QVariant", lambda self: {
        "titles": [s.title for s in self.script.sections], "bySentence": [s.section for s in self.script.sentences],
    } if self.script is not None else {}, notify=loadedChanged)
    markers = Property("QVariant", _markers, notify=editChanged)
    words = Property("QVariant", _words, notify=loadedChanged)
    canReset = Property(bool, lambda self: not self._is_automatic(), notify=resetChanged)
    editDuration = Property(float, lambda self: self.edit.duration if self.edit else 0.0, notify=editChanged)
    staleSentences = Property("QVariant", _stale_sentences, notify=editChanged)
    canUndo = Property(bool, lambda self: bool(self.history and self.history.undo_stack), notify=editChanged)
    canRedo = Property(bool, lambda self: bool(self.history and self.history.redo_stack), notify=editChanged)
    rendering = Property(bool, lambda self: self._rendering, notify=renderChanged)
    renderProgress = Property(float, lambda self: self._render_progress, notify=renderChanged)
