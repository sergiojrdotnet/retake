from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..script.lexicon import atomic_write

MIN_CLIP = 0.05


@dataclass
class Clip:
    id: int
    start: float
    end: float
    take: int | None = None
    sentence: int | None = None
    kind: str = "take"
    label: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Edit:
    clips: list[Clip] = field(default_factory=list)
    source_duration: float = 0.0
    order: str = "source"
    crossfade_ms: int = 15
    camera_crossfade_ms: int = 0
    rules: dict = field(default_factory=dict)
    next_id: int = 1

    def add(self, start: float, end: float, **fields) -> Clip:
        clip = Clip(self.next_id, max(0.0, start), min(end, self.source_duration or end), **fields)
        self.next_id += 1
        self.clips.append(clip)
        self.normalize()
        return clip

    def normalize(self) -> None:
        self.clips = [c for c in self.clips if c.end - c.start >= MIN_CLIP]
        self.clips.sort(key=lambda c: (c.start, c.id))
        merged: list[Clip] = []
        for clip in self.clips:
            if merged and clip.start < merged[-1].end - 1e-6 and self.order == "source":
                previous = merged[-1]
                previous.end = max(previous.end, clip.end)
                continue
            merged.append(clip)
        self.clips = merged

    def timeline(self) -> list[Clip]:
        if self.order != "script":
            return list(self.clips)
        anchored: list[tuple[float, float, int, Clip]] = []
        last_sentence = -1.0
        for clip in self.clips:
            if clip.sentence is not None:
                last_sentence = clip.sentence
                anchored.append((float(clip.sentence), 0.0, clip.id, clip))
            else:
                anchored.append((last_sentence, 1.0 + clip.start, clip.id, clip))
        return [entry[3] for entry in sorted(anchored, key=lambda e: (e[0], e[1], e[2]))]

    @property
    def duration(self) -> float:
        return sum(c.duration for c in self.clips)

    def clip_at(self, source_time: float) -> Clip | None:
        return next((c for c in self.clips if c.start <= source_time < c.end), None)

    def gap_at(self, source_time: float) -> tuple[float, float] | None:
        if self.clip_at(source_time):
            return None
        before = max((c.end for c in self.clips if c.end <= source_time), default=0.0)
        after = min((c.start for c in self.clips if c.start > source_time), default=self.source_duration)
        return before, after

    def to_output(self, source_time: float) -> float | None:
        offset = 0.0
        for clip in self.timeline():
            if clip.start <= source_time <= clip.end:
                return offset + source_time - clip.start
            offset += clip.duration
        return None

    def to_source(self, output_time: float) -> float | None:
        offset = 0.0
        for clip in self.timeline():
            if offset <= output_time <= offset + clip.duration:
                return clip.start + output_time - offset
            offset += clip.duration
        return None

    def split(self, source_time: float) -> bool:
        clip = self.clip_at(source_time)
        if clip is None or source_time - clip.start < MIN_CLIP or clip.end - source_time < MIN_CLIP:
            return False
        tail = Clip(self.next_id, source_time, clip.end, clip.take, clip.sentence, clip.kind, clip.label)
        self.next_id += 1
        clip.end = source_time
        self.clips.append(tail)
        self.clips.sort(key=lambda c: (c.start, c.id))
        return True

    def remove(self, clip_id: int) -> bool:
        before = len(self.clips)
        self.clips = [c for c in self.clips if c.id != clip_id]
        return len(self.clips) != before

    def restore(self, start: float, end: float, **fields) -> Clip:
        return self.add(start, end, kind=fields.pop("kind", "manual"), **fields)

    def set_edge(self, clip_id: int, edge: str, source_time: float) -> bool:
        clip = next((c for c in self.clips if c.id == clip_id), None)
        if clip is None:
            return False
        neighbours = sorted((c for c in self.clips if c.id != clip_id), key=lambda c: c.start)
        if edge == "start":
            limit = max((c.end for c in neighbours if c.end <= clip.start + 1e-6), default=0.0)
            clip.start = min(max(source_time, limit), clip.end - MIN_CLIP)
        else:
            limit = min((c.start for c in neighbours if c.start >= clip.end - 1e-6), default=self.source_duration or source_time)
            clip.end = max(min(source_time, limit), clip.start + MIN_CLIP)
        return True

    def replace_take(self, sentence: int, start: float, end: float, take: int) -> None:
        self.clips = [c for c in self.clips if c.sentence != sentence]
        self.add(start, end, take=take, sentence=sentence, kind="take")

    def edges(self) -> list[float]:
        points = set()
        for clip in self.clips:
            points.add(round(clip.start, 3))
            points.add(round(clip.end, 3))
        return sorted(points)

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Edit:
        clips = [Clip(**c) for c in data.get("clips", [])]
        fields = {k: v for k, v in data.items() if k != "clips"}
        return cls(clips=clips, **fields)

    def save(self, path: Path) -> None:
        atomic_write(path, json.dumps(self.as_dict(), indent=1))

    @classmethod
    def load(cls, path: Path) -> Edit:
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


class History:
    def __init__(self, edit: Edit, limit: int = 200):
        self.edit = edit
        self.undo_stack: list[Edit] = []
        self.redo_stack: list[Edit] = []
        self.limit = limit

    def checkpoint(self) -> None:
        self.undo_stack.append(copy.deepcopy(self.edit))
        self.undo_stack = self.undo_stack[-self.limit:]
        self.redo_stack.clear()

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append(copy.deepcopy(self.edit))
        self.edit = self.undo_stack.pop()
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append(copy.deepcopy(self.edit))
        self.edit = self.redo_stack.pop()
        return True
