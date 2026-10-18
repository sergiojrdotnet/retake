from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

WORD = "word"
CUE = "cue"
PAUSE = "pause"
TEXT = "text"

SPOKEN = "spoken"
ADLIB = "adlib"


@dataclass
class Word:
    index: int
    sentence: int
    position: int
    display: str
    variants: list[list[str]]
    override_ipa: str | None = None
    emphasis: bool = False
    spoken: str | None = None

    @property
    def key(self) -> str:
        return lexicon_key(self.display)


@dataclass
class Token:
    kind: str
    text: str
    word: Word | None = None
    value: str = ""


@dataclass
class Sentence:
    index: int
    paragraph: int
    section: int
    kind: str = SPOKEN
    tokens: list[Token] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)
    note: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return " ".join(w.display for w in self.words)

    @property
    def display_text(self) -> str:
        return " ".join(t.text for t in self.tokens if t.kind in (WORD, TEXT))

    @property
    def trackable(self) -> bool:
        return self.kind == SPOKEN and bool(self.words)


@dataclass
class Paragraph:
    index: int
    section: int
    sentences: list[int] = field(default_factory=list)


@dataclass
class Section:
    index: int
    title: str
    level: int
    first_sentence: int
    meta: dict = field(default_factory=dict)


@dataclass
class Script:
    path: Path | None
    title: str
    language: str
    sections: list[Section]
    paragraphs: list[Paragraph]
    sentences: list[Sentence]
    words: list[Word]

    def next_sentence(self, index: int) -> int | None:
        for sentence in self.sentences[index + 1:]:
            if sentence.kind == SPOKEN and sentence.words or sentence.kind == ADLIB:
                return sentence.index
        return None

    def previous_sentence(self, index: int) -> int | None:
        for sentence in reversed(self.sentences[:index]):
            if sentence.words or sentence.kind == ADLIB:
                return sentence.index
        return None


_KEY = re.compile(r"[^\w'\-]+", re.UNICODE)


def lexicon_key(display: str) -> str:
    text = display.replace("’", "'").lower()
    return _KEY.sub("", text).strip("'-")
