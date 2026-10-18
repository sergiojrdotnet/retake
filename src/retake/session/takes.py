from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field

RECORDING = "recording"
COMPLETE = "complete"
REJECTED = "rejected"

COMMAND = "command"
TTS = "tts"
OFF_SCRIPT = "off-script"
CHAPTER = "chapter"
MARK = "mark"
PAUSE = "pause"
ADLIB = "adlib"
FLAG = "flag"
FILLER = "filler"
DRILL = "drill"


@dataclass
class WordTiming:
    word: int
    text: str
    start: float
    end: float
    score: float | None = None
    heard: str = ""


@dataclass
class Take:
    id: int
    sentence: int | None
    number: int
    start: float
    end: float | None = None
    status: str = RECORDING
    reason: str = ""
    text: str = ""
    words: list[WordTiming] = field(default_factory=list)
    score: float | None = None
    flagged: list[dict] = field(default_factory=list)
    deviations: list[dict] = field(default_factory=list)
    stale: bool = False

    @property
    def duration(self) -> float:
        return (self.end or self.start) - self.start

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Take:
        words = [WordTiming(**w) for w in data.pop("words", [])]
        return cls(words=words, **data)


@dataclass
class Marker:
    id: int
    kind: str
    start: float
    end: float
    label: str = ""
    data: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class TakeLog:
    """Every take and marker of a recording. A log with a sink hands itself over on each change
    (to the project's .retake file); one without is kept in memory only."""

    sink: Callable[[dict], None] | None = None
    takes: list[Take] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def new_take(self, sentence: int | None, start: float, text: str = "") -> Take:
        number = 1 + sum(1 for t in self.takes if t.sentence == sentence and sentence is not None)
        if sentence is None:
            number = len(self.takes) + 1
        take = Take(len(self.takes) + 1, sentence, number, start, text=text)
        self.takes.append(take)
        self.save()
        return take

    def add_marker(self, kind: str, start: float, end: float | None = None, label: str = "", **data) -> Marker:
        marker = Marker(len(self.markers) + 1, kind, start, end if end is not None else start, label, data)
        self.markers.append(marker)
        self.save()
        return marker

    def take(self, take_id: int) -> Take | None:
        return next((t for t in self.takes if t.id == take_id), None)

    def markers_of(self, *kinds: str) -> list[Marker]:
        return [m for m in self.markers if m.kind in kinds]

    def as_dict(self) -> dict:
        return {"meta": self.meta, "takes": [t.as_dict() for t in self.takes], "markers": [m.as_dict() for m in self.markers]}

    def save(self) -> None:
        if self.sink is not None:
            self.sink(self.as_dict())

    @classmethod
    def from_dict(cls, data: dict, sink: Callable[[dict], None] | None = None) -> TakeLog:
        return cls(sink, [Take.from_dict(t) for t in data.get("takes", [])], [Marker(**m) for m in data.get("markers", [])], data.get("meta", {}))
