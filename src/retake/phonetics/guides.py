from __future__ import annotations

from dataclasses import dataclass, field

from ..languages.packs import LanguagePack
from ..script.lexicon import Lexicon
from ..script.model import Script, Word
from . import espeak, ipa as ipa_parser
from .arpabet import Phone
from .cmudict import cmudict
from .respell import Respeller, ipa as render_ipa
from .syllables import count as syllable_count

ALL = "all"
HARD = "hard"
FLAGGED = "flagged"


@dataclass
class Guide:
    key: str
    phones: list[Phone]
    source: str
    ipa: str = ""
    respell: str = ""
    native: str = ""
    syllables: int = 0
    heteronym: bool = False
    variants: int = 0

    @property
    def oov(self) -> bool:
        return self.source in ("espeak", "none")

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "ipa": self.ipa,
            "respell": self.respell,
            "native": self.native,
            "syllables": self.syllables,
            "source": self.source,
            "oov": self.oov,
            "heteronym": self.heteronym,
            "variants": self.variants,
        }


@dataclass
class GuideBook:
    by_key: dict[str, Guide] = field(default_factory=dict)
    by_word: dict[int, Guide] = field(default_factory=dict)

    def for_word(self, word: Word) -> Guide | None:
        return self.by_word.get(word.index) or self.by_key.get(word.key)


class GuideBuilder:
    def __init__(self, script_pack: LanguagePack, native_pack: LanguagePack | None, lexicon: Lexicon | None = None):
        self.script_pack = script_pack
        self.native_pack = native_pack
        self.lexicon = lexicon or Lexicon(None)
        self.dictionary = cmudict() if script_pack.lexicon == "cmudict" else None
        self.script_respeller = Respeller(script_pack.respelling) if script_pack.respelling else None
        same = native_pack is None or native_pack.code == script_pack.code
        self.native_respeller = (
            Respeller(native_pack.respelling) if native_pack and native_pack.respelling and not same else None
        )

    def build(self, script: Script) -> GuideBook:
        book = GuideBook()
        pending: dict[str, Word] = {}
        for word in script.words:
            key = word.key
            if word.override_ipa:
                book.by_word[word.index] = self._from_ipa(key, word.override_ipa, "override")
                continue
            if key in book.by_key or key in pending:
                continue
            guide = self._known(word)
            if guide:
                book.by_key[key] = guide
            else:
                pending[key] = word
        if pending:
            words = list(pending.values())
            texts = [w.display.strip(".,;:!?\"'()[]") or w.key for w in words]
            try:
                results = espeak.ipa_batch(texts, self.script_pack.espeak_voice)
            except (espeak.EspeakMissing, OSError):
                results = [""] * len(words)
            for word, result in zip(words, results):
                if result:
                    book.by_key[word.key] = self._from_ipa(word.key, result, "espeak")
                else:
                    book.by_key[word.key] = Guide(word.key, [], "none")
        return book

    def guide_for_text(self, text: str) -> Guide:
        key = text.lower().strip()
        phones = self.dictionary.first(key) if self.dictionary else None
        if phones:
            return self._finish(Guide(key, phones, "cmudict", variants=len(self.dictionary.lookup(key))))
        return self._from_ipa(key, espeak.ipa(text, self.script_pack.espeak_voice), "espeak")

    def _known(self, word: Word) -> Guide | None:
        key = word.key
        custom = self.lexicon.word_ipa(key)
        if custom:
            return self._from_ipa(key, custom, "lexicon")
        if not self.dictionary:
            return None
        variants = self.dictionary.lookup(key)
        if variants:
            return self._finish(Guide(key, variants[0], "cmudict", variants=len(variants)))
        for variant in word.variants:
            parts = [self.dictionary.first(token) for token in variant]
            if all(parts):
                phones = [phone for part in parts for phone in part]
                return self._finish(Guide(key, phones, "cmudict", variants=1))
        return None

    def _from_ipa(self, key: str, text: str, source: str) -> Guide:
        phones = ipa_parser.to_phones(text)
        return self._finish(Guide(key, phones, source))

    def _finish(self, guide: Guide) -> Guide:
        guide.syllables = syllable_count(guide.phones)
        guide.heteronym = guide.key in self.script_pack.heteronyms
        if guide.phones:
            guide.ipa = render_ipa(guide.phones)
            if self.script_respeller:
                guide.respell = self.script_respeller.render(guide.phones)
            if self.native_respeller:
                guide.native = self.native_respeller.render(guide.phones)
        return guide


def is_hard(guide: Guide | None, flagged: bool) -> bool:
    if flagged:
        return True
    if guide is None:
        return False
    return guide.syllables >= 3 or guide.oov or guide.heteronym or guide.source in ("override", "lexicon")


def visible(guide: Guide | None, scope: str, flagged: bool) -> bool:
    if guide is None or not guide.phones:
        return False
    if scope == ALL:
        return True
    if scope == FLAGGED:
        return flagged
    return is_hard(guide, flagged)
