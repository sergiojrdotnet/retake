from __future__ import annotations

import difflib
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .edit.trim import Segment
from .session.takes import REJECTED, Marker, Take, TakeLog, WordTiming
from .store import Store

EXTENSION = ".retake"
VIDEO_SUFFIXES = (".mkv", ".mp4", ".mov", ".webm")


@dataclass
class Part:
    """One continuous recording of an item.

    Parts sit end to end on a single virtual timeline: a take at local time t in part k is
    stored at part.start + t, so takes, markers and the edit keep using one clock."""

    index: int
    audio: Path
    start: float
    duration: float
    video: Path | None = None
    video_offset: float = 0.0
    kind: str = "recording"
    created: str = ""
    sentences: tuple[int, ...] = ()
    video_segments: tuple = ()

    @property
    def end(self) -> float:
        return self.start + self.duration


def slug(text: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "-", text.strip()).strip("-.")
    return cleaned or "item"


def file_name(text: str) -> str:
    """A readable file or folder name: spaces stay, only characters a path can't hold go."""
    cleaned = re.sub(r"[/\\\x00-\x1f]+", " ", text).strip(" .")
    return " ".join(cleaned.split()) or "Project"


def relative(directory: Path, path: Path) -> str:
    try:
        return str(path.relative_to(directory))
    except ValueError:
        return str(path)


def _resolve(directory: Path, file: str | None) -> Path | None:
    if not file:
        return None
    path = directory / file
    return path if path.exists() else None


def audio_duration(path: Path) -> float:
    try:
        import soundfile

        info = soundfile.info(str(path))
        if info.frames > 0:
            return info.frames / info.samplerate
    except Exception:
        pass
    try:
        from .edit import media

        return media.probe(path).duration
    except Exception:
        return 0.0


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Item:
    """A script inside a project. Its media (audio and video per part, and the exports) sit in its
    own folder; everything else is in the project's .retake file."""

    def __init__(self, project: Project, data: dict):
        self.project = project
        self.data = data

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def title(self) -> str:
        return self.data.get("title") or self.id

    @property
    def folder(self) -> Path:
        return self.project.directory / self.data.get("folder", self.id)

    @property
    def script_file(self) -> Path | None:
        name = self.data.get("script")
        return self.project.directory / name if name else None

    @property
    def source(self) -> Path | None:
        source = self.data.get("source")
        return Path(source) if source else None

    @property
    def out_dir(self) -> Path:
        return self.folder / "out"

    @property
    def parts(self) -> list[Part]:
        parts = []
        start = 0.0
        for entry in self.data.get("parts", []):
            audio = self.folder / entry["audio"]
            duration = float(entry.get("duration") or 0.0)
            if duration <= 0 and audio.exists():
                duration = audio_duration(audio)
            video = entry.get("video") or {}
            parts.append(Part(
                index=int(entry.get("index", len(parts) + 1)), audio=audio, start=start, duration=duration,
                video=_resolve(self.folder, video.get("file")), video_offset=float(video.get("offset", 0.0)),
                kind=entry.get("kind", "recording"), created=entry.get("created", ""), sentences=tuple(entry.get("sentences", ())),
                video_segments=tuple(Segment.from_dict(s) for s in video.get("segments", [])),
            ))
            start += duration
        return parts

    @property
    def duration(self) -> float:
        parts = self.parts
        return parts[-1].end if parts else 0.0

    @property
    def has_video(self) -> bool:
        return any(part.video is not None for part in self.parts)

    def boundaries(self) -> list[float]:
        return [part.start for part in self.parts[1:]]

    def part_at(self, t: float) -> Part | None:
        parts = self.parts
        for part in parts:
            if part.start <= t < part.end:
                return part
        return parts[-1] if parts and t >= parts[-1].start else None

    def next_part(self) -> tuple[int, Path]:
        used = {int(entry.get("index", 0)) for entry in self.data.get("parts", [])}
        used |= {int(m.group(1)) for f in self.folder.glob("part-*.flac") if (m := re.match(r"part-(\d+)$", f.stem))}
        index = max(used, default=0) + 1
        return index, self.folder / f"part-{index:03d}.flac"

    def add_part(self, index: int, audio: Path, duration: float, kind: str = "recording", video: Path | None = None,
                 video_offset: float = 0.0, video_method: str = "none", t0_monotonic: float | None = None,
                 sentences: list[int] | None = None, engines: dict | None = None, video_segments: list[dict] | None = None) -> Part:
        entry = {
            "index": index, "audio": relative(self.folder, audio), "duration": duration, "kind": kind, "created": _now(),
            "t0_monotonic": t0_monotonic,
            "video": {"file": relative(self.folder, video), "offset": video_offset, "method": video_method} if video else None,
        }
        if video and video_segments:
            entry["video"]["segments"] = video_segments
        if sentences:
            entry["sentences"] = sorted(sentences)
        if engines:
            entry["engines"] = engines
        self.data.setdefault("parts", []).append(entry)
        self.project.save()
        return self.parts[-1]

    def sources(self) -> list:
        from .edit.render import Source

        return [Source(p.audio, p.start, p.duration, p.video, p.video_offset, list(p.video_segments)) for p in self.parts]

    def load_script(self):
        """The script the takes refer to: the snapshot taken at the last recording, else the project copy."""
        from .languages import packs
        from .script.lexicon import Lexicon
        from .script.parser import parse

        if self.script_file is None:
            return None
        text = self.snapshot
        try:
            if text is None:
                text = self.script_file.read_text(encoding="utf-8")
            return parse(text, packs.get(self.project.language), path=self.script_file, spoken=Lexicon.for_script(self.script_file).spoken_forms())
        except (OSError, KeyError, ValueError):
            return None

    @property
    def snapshot(self) -> str | None:
        return self.project.store.snapshot(self.id)

    def save_snapshot(self, text: str) -> None:
        self.project.store.save_snapshot(self.id, text)

    def load_edit(self):
        from .edit.edl import Edit

        data = self.project.store.edit(self.id)
        return Edit.from_dict(data) if data else None

    def save_edit(self, edit) -> None:
        self.project.store.save_edit(self.id, edit.as_dict())

    def load_takes(self) -> TakeLog:
        store, item_id = self.project.store, self.id
        return TakeLog.from_dict(store.log(item_id) or {}, sink=lambda data: store.save_log(item_id, data))

    def recording_log(self, part: int) -> TakeLog:
        """The take log of the part being recorded, kept in the .retake file as it goes so a crash
        loses nothing; the takes join the item's once the part is finished."""
        store, item_id = self.project.store, self.id
        return TakeLog(sink=lambda data: store.save_recording(item_id, part, data))

    def unfinished_recording(self, part: int) -> TakeLog | None:
        data = self.project.store.recording(self.id, part)
        return TakeLog.from_dict(data) if data else None

    def finish_recording(self, part_log: TakeLog, index: int, audio: Path, duration: float, **part) -> list[Take]:
        """Moves a finished part's takes onto the item's timeline and adds the part, in one write."""
        with self.project.store.batch():
            added = merge_takes(self.load_takes(), part_log, self.duration)
            self.add_part(index, audio, duration, **part)
            self.project.store.drop_recording(self.id, index)
        return added

    def recording_files(self) -> list[Path]:
        """The media recorded for this item (every part's audio and video) and its exports. The
        script itself, in the project's scripts folder, isn't among them."""
        folder = self.folder
        files = [p for p in folder.glob("part-*") if p.is_file()]
        files += [p for p in folder.glob(".part-*") if p.is_file()]
        return files + [folder / "out"] if (folder / "out").exists() else files

    def forget_recordings(self) -> None:
        with self.project.store.batch():
            self.data["parts"] = []
            self.project.store.forget(self.id)
            self.project.save()

    def remove_part(self, index: int) -> list[Path]:
        """Takes one recording out. Its takes, markers and edit clips go; whatever came after slides back
        to close the gap on the timeline, hand edits included. Returns the files that belonged to it."""
        part = next((p for p in self.parts if p.index == index), None)
        if part is None:
            return []
        start, end, gap = part.start, part.end, part.duration

        def inside(t: float) -> bool:
            return start - 1e-6 <= t < end - 1e-6

        def moved(t: float) -> float:
            return t - gap if t >= end - 1e-6 else t

        log = self.load_takes()
        log.takes = [t for t in log.takes if not inside(t.start)]
        for take in log.takes:
            take.start = moved(take.start)
            take.end = None if take.end is None else moved(take.end)
            for word in take.words:
                word.start, word.end = moved(word.start), moved(word.end)
            take.flagged = [{**f, **{k: moved(f[k]) for k in ("start", "end") if isinstance(f.get(k), (int, float))}} for f in take.flagged]
        log.markers = [m for m in log.markers if not inside(m.start)]
        for marker in log.markers:
            marker.start, marker.end = moved(marker.start), moved(marker.end)
        edit = self.load_edit()
        with self.project.store.batch():
            log.save()
            if edit is not None:
                edit.clips = [c for c in edit.clips if not inside(c.start)]
                for clip in edit.clips:
                    clip.start, clip.end = moved(clip.start), moved(clip.end)
                edit.source_duration = max(0.0, edit.source_duration - gap)
                self.save_edit(edit)
            self.data["parts"] = [e for e in self.data.get("parts", []) if int(e.get("index", 0)) != index]
            self.project.save()
        stem = f"part-{index:03d}"
        return sorted(f for pattern in (f"{stem}.*", f".{stem}.*") for f in self.folder.glob(pattern) if f.is_file())

    def status(self, script=None) -> dict:
        """Sentences with a good take, out of the script's trackable sentences."""
        data = self.project.store.log(self.id) or {}
        recorded = {t["sentence"] for t in data.get("takes", []) if t.get("status") == "complete" and t.get("sentence") is not None}
        total = sum(1 for s in script.sentences if s.trackable) if script is not None else 0
        return {"recorded": len(recorded), "total": total, "duration": self.duration, "parts": len(self.data.get("parts", []))}


class Project:
    def __init__(self, path: Path, store: Store, data: dict):
        self.path = path
        self.store = store
        self.data = data

    @property
    def directory(self) -> Path:
        return self.path.parent

    @property
    def title(self) -> str:
        return self.data.get("title") or self.path.stem

    @property
    def language(self) -> str:
        return self.data.get("language", "en")

    @property
    def items(self) -> list[Item]:
        return [Item(self, entry) for entry in self.data.get("items", [])]

    def item(self, item_id: str) -> Item | None:
        return next((item for item in self.items if item.id == item_id), None)

    @property
    def last_opened(self) -> tuple[str, str] | None:
        """The script open last and its view ("prompter" or "studio"), while it's still in the project."""
        last = self.data.get("last_opened") or {}
        return (last["item"], last.get("view", "prompter")) if self.item(last.get("item", "")) else None

    def remember_opened(self, item_id: str, view: str) -> None:
        self.data["last_opened"] = {"item": item_id, "view": view}
        self.store.save_value("last_opened", self.data["last_opened"])

    # Creating, loading and saving

    @classmethod
    def create(cls, directory: Path, title: str, language: str = "en", native: str = "") -> Project:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{file_name(title)}{EXTENSION}"
        data = {"title": title, "created": _now(), "modified": _now(), "language": language, "native": native, "items": []}
        project = cls(path, Store(path, create=True), data)
        project.save()
        return project

    @classmethod
    def load(cls, path: Path) -> Project:
        """Opens a .retake file, or the project folder holding one."""
        path = Path(path).expanduser()
        if path.is_dir():
            found = sorted(path.glob(f"*{EXTENSION}"))
            if not found:
                raise ValueError(f"No Retake project in {path}")
            path = found[0]
        store = Store(path)
        return cls(path, store, {**store.project(), "items": store.items()})

    def save(self) -> None:
        self.data["modified"] = _now()
        self.store.save_project({k: v for k, v in self.data.items() if k != "items"}, self.data.get("items", []))

    def close(self) -> None:
        self.store.close()

    # Items

    def _unique_id(self, base: str) -> str:
        taken = {item.id for item in self.items} | {p.name for p in self.directory.iterdir() if p.is_dir()}
        candidate, number = slug(base), 2
        while candidate in taken:
            candidate = f"{slug(base)}-{number}"
            number += 1
        return candidate

    def add_script(self, source: Path, title: str = "") -> Item:
        """Copies a script, and its lexicon when there is one, into the project."""
        source = source.expanduser().resolve()
        item_id = self._unique_id(source.stem)
        scripts = self.directory / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        target = scripts / f"{item_id}{source.suffix or '.md'}"
        shutil.copy2(source, target)
        lexicon = source.with_name(source.stem + ".lexicon.tsv")
        if lexicon.exists():
            shutil.copy2(lexicon, target.with_name(target.stem + ".lexicon.tsv"))
        entry = {"id": item_id, "title": title or source.stem, "folder": item_id,
                 "script": relative(self.directory, target), "source": str(source), "added": _now(), "parts": []}
        self.data.setdefault("items", []).append(entry)
        (self.directory / item_id).mkdir(parents=True, exist_ok=True)
        self.save()
        return Item(self, entry)

    def remove_item(self, item_id: str) -> None:
        """Takes an item, and its takes and edit, off the project; its folder of media stays on disk."""
        with self.store.batch():
            self.data["items"] = [entry for entry in self.data.get("items", []) if entry["id"] != item_id]
            self.store.forget(item_id)
            self.save()

    def rename_item(self, item_id: str, title: str) -> None:
        item = self.item(item_id)
        if item is not None and title.strip():
            item.data["title"] = title.strip()
            self.save()

    def reimport(self, item_id: str) -> bool:
        """Copies the original script over the project's copy again."""
        item = self.item(item_id)
        if item is None or item.source is None or not item.source.exists() or item.script_file is None:
            return False
        shutil.copy2(item.source, item.script_file)
        lexicon = item.source.with_name(item.source.stem + ".lexicon.tsv")
        if lexicon.exists():
            shutil.copy2(lexicon, item.script_file.with_name(item.script_file.stem + ".lexicon.tsv"))
        return True

    def find_by_source(self, source: Path) -> Item | None:
        wanted = source.expanduser().resolve()
        return next((item for item in self.items if item.source and item.source.expanduser().resolve() == wanted), None)


# Moving recordings onto an item's timeline


def merge_takes(item_log: TakeLog, part_log: TakeLog, offset: float) -> list[Take]:
    """Moves a part's takes and markers onto the item's timeline, renumbering them."""
    added = []
    next_take = max((t.id for t in item_log.takes), default=0) + 1
    for take in part_log.takes:
        number = 1 + sum(1 for t in item_log.takes if t.sentence == take.sentence and take.sentence is not None)
        moved = Take(
            id=next_take, sentence=take.sentence, number=number if take.sentence is not None else next_take,
            start=take.start + offset, end=None if take.end is None else take.end + offset, status=take.status,
            reason=take.reason, text=take.text,
            words=[WordTiming(w.word, w.text, w.start + offset, w.end + offset, w.score, w.heard) for w in take.words],
            score=take.score,
            flagged=[{**f, **{k: f[k] + offset for k in ("start", "end") if isinstance(f.get(k), (int, float))}} for f in take.flagged],
            deviations=take.deviations,
        )
        item_log.takes.append(moved)
        added.append(moved)
        next_take += 1
    next_marker = max((m.id for m in item_log.markers), default=0) + 1
    for marker in part_log.markers:
        item_log.markers.append(Marker(next_marker, marker.kind, marker.start + offset, marker.end + offset, marker.label, dict(marker.data)))
        next_marker += 1
    item_log.save()
    return added


def _sentence_key(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s']", " ", text.lower()).split())


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.split(), b.split(), autojunk=False).ratio()


def sentence_map(old_script, new_script, threshold: float = 0.5) -> dict[int, tuple[int, bool] | None]:
    """Where each old sentence went after the script was edited: (new index, reworded) or None.

    Sentences are aligned in order; inside an edited stretch, a sentence that kept at least half
    of its words counts as reworded rather than gone, and a sentence moved elsewhere unchanged
    is still found."""
    old_keys = [_sentence_key(s.text) for s in old_script.sentences]
    new_keys = [_sentence_key(s.text) for s in new_script.sentences]
    mapping: dict[int, tuple[int, bool] | None] = {}
    used: set[int] = set()
    matcher = difflib.SequenceMatcher(None, old_keys, new_keys, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                mapping[i1 + offset] = (j1 + offset, False)
                used.add(j1 + offset)
        elif tag == "replace":
            for i in range(i1, i2):
                choices = [(j, _similarity(old_keys[i], new_keys[j])) for j in range(j1, j2) if j not in used]
                best = max(choices, key=lambda pair: pair[1], default=None)
                if best and best[1] >= threshold:
                    mapping[i] = (best[0], True)
                    used.add(best[0])
    positions: dict[str, list[int]] = {}
    for j, key in enumerate(new_keys):
        positions.setdefault(key, []).append(j)
    for i, key in enumerate(old_keys):
        if i in mapping:
            continue
        moved = [j for j in positions.get(key, []) if j not in used]
        if moved:
            mapping[i] = (moved[0], False)
            used.add(moved[0])
        else:
            mapping[i] = None
    return mapping


@dataclass
class Remap:
    reworded: list[int]
    lost: int


def remap_item(item: Item, old_script, new_script) -> Remap:
    """Re-points takes and the edit at an edited script. Takes on a reworded sentence stay, marked
    stale so they can be re-recorded; takes whose sentence is gone are set aside."""
    mapping = sentence_map(old_script, new_script)
    reworded: set[int] = set()
    lost = 0
    log = item.load_takes()
    for take in log.takes:
        if take.sentence is None:
            continue
        target = mapping.get(take.sentence)
        if target is None:
            take.sentence = None
            if take.status != REJECTED:
                take.status, take.reason = REJECTED, "script changed"
            lost += 1
            continue
        take.sentence, changed = target
        if changed:
            take.stale = True
            if take.status == "complete":
                reworded.add(take.sentence)
    edit = item.load_edit()
    with item.project.store.batch():
        log.save()
        if edit is not None:
            kept = []
            for clip in edit.clips:
                if clip.sentence is None:
                    kept.append(clip)
                elif mapping.get(clip.sentence) is not None:
                    clip.sentence = mapping[clip.sentence][0]
                    kept.append(clip)
            edit.clips = kept
            item.save_edit(edit)
    return Remap(sorted(reworded), lost)


def sync_script(item: Item) -> Remap | None:
    """Brings an item's snapshot up to date with its script, re-pointing takes when the text changed."""
    if item.script_file is None or not item.script_file.exists():
        return None
    current = item.script_file.read_text(encoding="utf-8")
    snapshot = item.snapshot
    result = None
    if snapshot is not None and item.parts and snapshot != current:
        from .languages import packs
        from .script.parser import parse

        pack = packs.get(item.project.language)
        result = remap_item(item, parse(snapshot, pack, path=item.script_file), parse(current, pack, path=item.script_file))
    if result is not None or snapshot is None:
        item.save_snapshot(current)
    return result


def recover_parts(item: Item) -> list[int]:
    """Adds parts left behind by a crash: audio on disk with no part in the project, and the takes
    recorded with it."""
    known = {int(entry.get("index", 0)) for entry in item.data.get("parts", [])}
    recovered = []
    for audio in sorted(item.folder.glob("part-*.flac")):
        match = re.match(r"part-(\d+)$", audio.stem)
        if not match or int(match.group(1)) in known:
            continue
        index = int(match.group(1))
        duration = audio_duration(audio)
        if duration <= 0:
            continue
        video = next((f for f in sorted(item.folder.glob(f"part-{index:03d}.*")) if f.suffix in VIDEO_SUFFIXES), None)
        item.finish_recording(item.unfinished_recording(index) or TakeLog(), index, audio, duration, kind="recovered", video=video)
        recovered.append(index)
    return recovered


# Finding projects


def new_directory(base: Path, title: str) -> Path:
    stem = file_name(title)
    candidate, number = base / stem, 2
    while candidate.exists():
        candidate = base / f"{stem} ({number})"
        number += 1
    return candidate


def known_projects(base: Path, recent: list[str] | None = None) -> list[Project]:
    """Projects in the projects folder plus recently opened ones that live anywhere else."""
    found: dict[Path, Project] = {}
    candidates = [d for d in base.iterdir() if d.is_dir()] if base.is_dir() else []
    candidates += [Path(p) for p in recent or []]
    for candidate in candidates:
        try:
            project = Project.load(candidate)
        except (OSError, ValueError):
            continue
        if project.path.resolve() in found:
            project.close()
            continue
        found[project.path.resolve()] = project
    return list(found.values())


def list_projects(base: Path, recent: list[str] | None = None) -> list[dict]:
    """Known projects, newest first."""
    rows = []
    for project in known_projects(base, recent):
        items = project.items
        rows.append({
            "path": str(project.path),
            "directory": str(project.directory),
            "title": project.title,
            "modified": project.data.get("modified") or "",
            "scripts": len(items),
            "recordings": sum(len(i.data.get("parts", [])) for i in items),
            "duration": sum(float(p.get("duration") or 0) for i in items for p in i.data.get("parts", [])),
        })
        project.close()
    rows.sort(key=lambda row: row["modified"] or "", reverse=True)
    return rows


def items_for_source(base: Path, source: Path, recent: list[str] | None = None) -> list[tuple[Project, Item]]:
    found = []
    for project in known_projects(base, recent):
        item = project.find_by_source(source)
        if item is not None:
            found.append((project, item))
    return found
