from __future__ import annotations

from dataclasses import dataclass, field

from .arpabet import PRIMARY, Phone, phone_to_ipa
from .syllables import syllabify


def ipa(phones: list[Phone]) -> str:
    parts = []
    for syllable in syllabify(phones):
        stress = next((p.stress for p in syllable if p.is_vowel), 0)
        mark = "ˈ" if stress == 1 else "ˌ" if stress == 2 else ""
        parts.append(mark + "".join(phone_to_ipa(p) for p in syllable))
    return "/" + "".join(parts) + "/"


@dataclass(frozen=True)
class Rule:
    phone: str
    value: str
    stressed: bool | None = None
    open_syllable: bool | None = None
    has_onset: bool | None = None
    between_vowels: bool | None = None
    word_initial: bool | None = None
    word_final: bool | None = None
    next_phones: tuple[str, ...] = ()
    next_output_prefix: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict) -> Rule:
        return cls(
            phone=data["phone"],
            value=data["value"],
            stressed=data.get("stressed"),
            open_syllable=data.get("open_syllable"),
            has_onset=data.get("has_onset"),
            between_vowels=data.get("between_vowels"),
            word_initial=data.get("word_initial"),
            word_final=data.get("word_final"),
            next_phones=tuple(data.get("next_phones", ())),
            next_output_prefix=tuple(data.get("next_output_prefix", ())),
        )


@dataclass
class RespellingTable:
    mapping: dict[str, str]
    rules: list[Rule] = field(default_factory=list)
    separator: str = "-"
    uppercase_stress: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> RespellingTable:
        return cls(
            mapping=dict(data["map"]),
            rules=[Rule.from_dict(r) for r in data.get("rules", [])],
            separator=data.get("separator", "-"),
            uppercase_stress=data.get("uppercase_stress", True),
        )


@dataclass
class _Context:
    phone: Phone
    index: int
    phones: list[Phone]
    syllable: list[Phone]


class Respeller:
    def __init__(self, table: RespellingTable):
        self.table = table

    def render(self, phones: list[Phone]) -> str:
        syllables = syllabify(phones)
        flat_index = 0
        rendered: list[tuple[str, bool]] = []
        contexts: list[list[_Context]] = []
        for syllable in syllables:
            row = []
            for phone in syllable:
                row.append(_Context(phone, flat_index, phones, syllable))
                flat_index += 1
            contexts.append(row)
        outputs: list[list[str]] = [[""] * len(row) for row in contexts]
        for s in reversed(range(len(contexts))):
            for p in reversed(range(len(contexts[s]))):
                following = self._following_output(outputs, s, p)
                outputs[s][p] = self._spell(contexts[s][p], following)
        for syllable, pieces in zip(syllables, outputs):
            stressed = any(ph.is_vowel and ph.stress == PRIMARY for ph in syllable)
            rendered.append(("".join(pieces), stressed))
        if self.table.uppercase_stress and len(rendered) > 1:
            parts = [text.upper() if stressed else text for text, stressed in rendered]
        else:
            parts = [text for text, _ in rendered]
        return self.table.separator.join(parts)

    @staticmethod
    def _following_output(outputs: list[list[str]], s: int, p: int) -> str:
        row = outputs[s]
        if p + 1 < len(row):
            return "".join(row[p + 1:])
        if s + 1 < len(outputs):
            return "".join(outputs[s + 1])
        return ""

    def _spell(self, ctx: _Context, following: str) -> str:
        for rule in self.table.rules:
            if rule.phone == ctx.phone.symbol and self._matches(rule, ctx, following):
                return rule.value
        return self.table.mapping.get(ctx.phone.symbol, ctx.phone.symbol.lower())

    @staticmethod
    def _matches(rule: Rule, ctx: _Context, following: str) -> bool:
        phones = ctx.phones
        if rule.stressed is not None and bool(ctx.phone.stress) != rule.stressed:
            return False
        if rule.open_syllable is not None:
            nucleus = next((i for i, p in enumerate(ctx.syllable) if p.is_vowel), None)
            is_open = nucleus is None or nucleus == len(ctx.syllable) - 1
            if is_open != rule.open_syllable:
                return False
        if rule.has_onset is not None:
            nucleus = next((i for i, p in enumerate(ctx.syllable) if p.is_vowel), 0)
            if (nucleus > 0) != rule.has_onset:
                return False
        if rule.word_initial is not None and (ctx.index == 0) != rule.word_initial:
            return False
        if rule.word_final is not None and (ctx.index == len(phones) - 1) != rule.word_final:
            return False
        if rule.between_vowels is not None:
            between = (
                0 < ctx.index < len(phones) - 1
                and phones[ctx.index - 1].is_vowel
                and phones[ctx.index + 1].is_vowel
            )
            if between != rule.between_vowels:
                return False
        if rule.next_phones:
            if ctx.index + 1 >= len(phones) or phones[ctx.index + 1].symbol not in rule.next_phones:
                return False
        if rule.next_output_prefix:
            if not following.lower().startswith(rule.next_output_prefix):
                return False
        return True
