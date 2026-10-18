from __future__ import annotations

import re
from pathlib import Path

from ..languages.packs import LanguagePack
from . import normalize
from .lexicon import Lexicon
from .model import (
    ADLIB, CUE, PAUSE, SPOKEN, TEXT, WORD,
    Paragraph, Script, Section, Sentence, Token, Word,
)

_FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.MULTILINE | re.DOTALL)
_NOTE = re.compile(r"\[\[.*?\]\]", re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BONEYARD = re.compile(r"/\*.*?\*/", re.DOTALL)
_ADLIB = re.compile(r"\(\s*AD-?LIB\s*\)(.*?)\(\s*/\s*AD-?LIB\s*\)", re.DOTALL | re.IGNORECASE)
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,}|={3,})\s*$")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_CODE = re.compile(r"`([^`]+)`")
_STRONG = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_EM = re.compile(r"(?<![\w*])([*_])(?=\S)(.+?)(?<=\S)\1(?![\w*])")
_TABLE = re.compile(r"^\|.*\|$")
_BEAT = re.compile(r"^b\d+[a-z]?$", re.IGNORECASE)
_INLINE = re.compile(
    r"(?P<anchor>\x03\d+\x03)"
    r"|(?P<override>\{[^{}|]+\|[^{}]+\})"
    r"|(?P<bracket>\[[^\[\]]+\])"
    r"|(?P<paren>\([^()]*\)[.,;:!?…\"'”’]*)"
    r"|(?<!\S)(?P<pause>//?)(?!\S)"
    r"|(?P<word>\S+)"
)
_TERMINATOR = re.compile(r"[.!?…]+[\"'”’)\]]*$")
_ADLIB_PLACEHOLDER = "\x00ADLIB{}\x00"
PLAIN_SUFFIXES = (".txt",)
_EMPH_ON, _EMPH_OFF = "\x01", "\x02"


def parse_file(path: Path, pack: LanguagePack, lexicon: Lexicon | None = None) -> Script:
    lexicon = lexicon or Lexicon.for_script(path)
    return parse(path.read_text(encoding="utf-8"), pack, path=path, spoken=lexicon.spoken_forms())


def parse(text: str, pack: LanguagePack, path: Path | None = None, spoken: dict[str, list[list[str]]] | None = None) -> Script:
    text = text.replace("\r\n", "\n")
    title = path.stem if path else "Untitled"
    if path is not None and path.suffix.lower() in PLAIN_SUFFIXES:
        return _parse_plain(text, pack, title, path, spoken or {})
    front = _FRONT_MATTER.match(text)
    if front:
        for line in front.group(1).splitlines():
            key, _, value = line.partition(":")
            if key.strip().lower() == "title" and value.strip():
                title = value.strip().strip("\"'")
        text = text[front.end():]
    adlibs: list[str] = []
    notes: list[str] = []

    def stash_adlib(match: re.Match) -> str:
        adlibs.append(match.group(1).strip())
        return "\n\n" + _ADLIB_PLACEHOLDER.format(len(adlibs) - 1) + "\n\n"

    def stash_note(match: re.Match) -> str:
        notes.append(match.group(0)[2:-2].strip())
        return f" \x03{len(notes) - 1}\x03 "

    text = _FENCE.sub("", text)
    text = _COMMENT.sub("", text)
    text = _NOTE.sub(stash_note, text)
    text = _BONEYARD.sub("", text)
    text = _ADLIB.sub(stash_adlib, text)

    builder = _Builder(pack, title, path, notes, spoken or {})
    for kind, payload in _blocks(text):
        if kind == "heading":
            level, heading = payload
            if level == 1 and not builder.has_title_heading:
                builder.title = _plain(heading)
                builder.has_title_heading = True
            builder.add_section(_plain(heading), level)
        elif kind == "adlib":
            builder.add_adlib(adlibs[payload])
        else:
            builder.add_paragraph(payload)
    return builder.build()


def _parse_plain(text: str, pack: LanguagePack, title: str, path: Path, spoken: dict[str, list[list[str]]]) -> Script:
    """A plain-text script: no markup at all. Blank lines separate paragraphs and every word is
    read; only the lexicon beside it adds pronunciations and spoken forms."""
    builder = _Builder(pack, title, path, [], spoken)
    for block in re.split(r"\n\s*\n", text):
        paragraph = " ".join(block.split())
        if paragraph:
            builder.add_paragraph(paragraph, plain=True)
    return builder.build()


def _blocks(text: str):
    paragraph: list[str] = []

    def flush():
        if paragraph:
            joined = " ".join(line.strip() for line in paragraph).strip()
            paragraph.clear()
            if joined:
                return [("paragraph", joined)]
        return []

    for raw in text.split("\n"):
        line = raw.rstrip()
        stripped = line.strip()
        placeholder = re.fullmatch(r"\x00ADLIB(\d+)\x00", stripped)
        if placeholder:
            yield from flush()
            yield ("adlib", int(placeholder.group(1)))
            continue
        heading = _HEADING.match(stripped)
        if heading:
            yield from flush()
            yield ("heading", (len(heading.group(1)), heading.group(2)))
            continue
        if not stripped or _RULE.match(stripped) or _TABLE.match(stripped):
            yield from flush()
            continue
        if stripped.startswith(">"):
            stripped = stripped.lstrip("> ").strip()
        item = _LIST_ITEM.match(stripped)
        if item:
            yield from flush()
            paragraph.append(item.group(1))
            continue
        paragraph.append(stripped)
    yield from flush()


def _plain(text: str) -> str:
    text = _IMAGE.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _CODE.sub(r"\1", text)
    text = _STRONG.sub(r"\2", text)
    text = _EM.sub(r"\2", text)
    return text.strip()


def _is_cue(content: str) -> bool:
    letters = [c for c in content if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


class _Builder:
    def __init__(self, pack: LanguagePack, title: str, path: Path | None, notes: list[str], spoken: dict[str, list[list[str]]]):
        self.pack = pack
        self.title = title
        self.path = path
        self.notes = notes
        self.spoken = spoken
        self.sticky: dict[str, str] = {}
        self.has_title_heading = False
        self.sections: list[Section] = []
        self.paragraphs: list[Paragraph] = []
        self.sentences: list[Sentence] = []
        self.words: list[Word] = []

    @property
    def section_index(self) -> int:
        return len(self.sections) - 1 if self.sections else -1

    def add_section(self, title: str, level: int) -> None:
        self.sections.append(Section(len(self.sections), title, level, len(self.sentences)))
        self.sticky = {}

    def apply_note(self, note: str) -> None:
        key, separator, value = note.partition(":")
        key, value = key.strip().lower(), value.strip()
        if not separator:
            if _BEAT.match(note.strip()):
                self.sticky["beat"] = note.strip()
            return
        section = self.sections[-1] if self.sections else None
        section_started = section is not None and any(s.words for s in self.sentences[section.first_sentence:])
        if section is not None and not section_started and key not in section.meta:
            section.meta[key] = value
        else:
            self.sticky[key] = value

    def sentence_meta(self) -> dict:
        meta = dict(self.sticky)
        if self.sections and "id" in self.sections[-1].meta:
            meta.setdefault("section_id", self.sections[-1].meta["id"])
        return meta

    def _new_paragraph(self) -> Paragraph:
        paragraph = Paragraph(len(self.paragraphs), self.section_index)
        self.paragraphs.append(paragraph)
        return paragraph

    def _new_sentence(self, paragraph: Paragraph, kind: str = SPOKEN) -> Sentence:
        sentence = Sentence(len(self.sentences), paragraph.index, self.section_index, kind)
        self.sentences.append(sentence)
        paragraph.sentences.append(sentence.index)
        return sentence

    def add_adlib(self, note: str) -> None:
        paragraph = self._new_paragraph()
        sentence = self._new_sentence(paragraph, ADLIB)
        sentence.note = _plain(" ".join(note.split()))

    def add_paragraph(self, text: str, plain: bool = False) -> None:
        paragraph = self._new_paragraph()
        tokens = [self._word(word, False) for word in text.split()] if plain else self._tokenize(text)
        sentence = self._new_sentence(paragraph)
        for token in tokens:
            if token.kind == "anchor":
                self.apply_note(token.value)
                continue
            starts_next = token.kind != PAUSE
            if starts_next and sentence.words and self._ended(sentence.words[-1].display):
                sentence = self._new_sentence(paragraph)
            if token.kind == WORD:
                if not sentence.words:
                    sentence.meta = self.sentence_meta()
                word = token.word
                word.index = len(self.words)
                word.sentence = sentence.index
                word.position = len(sentence.words)
                self.words.append(word)
                sentence.words.append(word)
            sentence.tokens.append(token)
        for s in list(self.sentences):
            if s.paragraph == paragraph.index and not s.tokens:
                self.sentences.remove(s)
                paragraph.sentences.remove(s.index)

    def _ended(self, display: str) -> bool:
        if not _TERMINATOR.search(display):
            return False
        bare = display.lower().rstrip("\"'”’)]")
        if bare in self.pack.abbreviations:
            return False
        if re.fullmatch(r"[a-z]\.", bare):
            return False
        return True

    def _tokenize(self, text: str) -> list[Token]:
        text = _IMAGE.sub("", text)
        text = _LINK.sub(r"\1", text)
        text = _CODE.sub(r"\1", text)
        text = _STRONG.sub(lambda m: _EMPH_ON + m.group(2) + _EMPH_OFF, text)
        text = _EM.sub(lambda m: _EMPH_ON + m.group(2) + _EMPH_OFF, text)
        tokens: list[Token] = []
        emphasis = False
        for match in _INLINE.finditer(text):
            if match.group("anchor"):
                tokens.append(Token("anchor", "", value=self.notes[int(match.group("anchor")[1:-1])]))
            elif match.group("override"):
                display, _, detail = match.group("override")[1:-1].partition("|")
                detail = detail.strip()
                if detail.startswith("="):
                    tokens.append(self._word(display.strip(), emphasis, spoken=detail[1:].strip()))
                else:
                    tokens.append(self._word(display.strip(), emphasis, detail))
            elif match.group("bracket"):
                tokens.append(Token(CUE, match.group("bracket")[1:-1].strip()))
            elif match.group("paren"):
                raw = match.group("paren")
                closing = raw.rindex(")")
                content, trailing = raw[1:closing].strip(), raw[closing + 1:]
                if _is_cue(content):
                    tokens.append(self._cue(content))
                    if trailing.strip(".,;:!?…\"'”’ "):
                        tokens.append(Token(TEXT, trailing))
                else:
                    for inner in ("(" + content + ")" + trailing).split():
                        tokens.append(self._word(inner, emphasis))
            elif match.group("pause"):
                tokens.append(Token(PAUSE, match.group("pause"), value="long" if match.group("pause") == "//" else "short"))
            else:
                raw = match.group("word")
                starts = _EMPH_ON in raw
                ends = _EMPH_OFF in raw
                display = raw.replace(_EMPH_ON, "").replace(_EMPH_OFF, "")
                if starts:
                    emphasis = True
                if display:
                    tokens.append(self._word(display, emphasis))
                if ends:
                    emphasis = False
        return tokens

    def _word(self, display: str, emphasis: bool, override: str | None = None, spoken: str | None = None) -> Token:
        if spoken:
            variants = normalize.word_variants(spoken, self.pack.numbers, self.spoken)
        else:
            if normalize.CURRENCY.match(display.strip(".,;:!?")):
                return Token(TEXT, display)
            variants = normalize.word_variants(display, self.pack.numbers, self.spoken)
        if not variants:
            return Token(TEXT, display)
        word = Word(-1, -1, -1, display, variants, override or None, emphasis, spoken or None)
        return Token(WORD, display, word=word)

    @staticmethod
    def _cue(content: str) -> Token:
        return Token(CUE, content)

    def build(self) -> Script:
        sentences = self.sentences
        mapping = {s.index: i for i, s in enumerate(sentences)}
        for i, sentence in enumerate(sentences):
            sentence.index = i
            for word in sentence.words:
                word.sentence = i
        for paragraph in self.paragraphs:
            paragraph.sentences = [mapping[s] for s in paragraph.sentences if s in mapping]
        for section in self.sections:
            later = [mapping[k] for k in mapping if k >= section.first_sentence]
            section.first_sentence = min(later) if later else len(sentences)
        paragraphs = [p for p in self.paragraphs if p.sentences]
        for i, paragraph in enumerate(paragraphs):
            paragraph.index = i
            for s in paragraph.sentences:
                sentences[s].paragraph = i
        return Script(self.path, self.title, self.pack.code, self.sections, paragraphs, sentences, self.words)
