from __future__ import annotations

import gzip
from functools import cache
from importlib import resources

from .arpabet import Phone, parse


class Lexicon:
    def __init__(self, entries: dict[str, list[list[Phone]]]):
        self._entries = entries

    def __contains__(self, word: str) -> bool:
        return word.lower() in self._entries

    def lookup(self, word: str) -> list[list[Phone]]:
        return self._entries.get(word.lower(), [])

    def first(self, word: str) -> list[Phone] | None:
        variants = self.lookup(word)
        return variants[0] if variants else None

    def __len__(self) -> int:
        return len(self._entries)


def parse_dict(lines) -> dict[str, list[list[Phone]]]:
    entries: dict[str, list[list[Phone]]] = {}
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        head, _, pron = line.partition(" ")
        word = head.split("(", 1)[0].lower()
        try:
            entries.setdefault(word, []).append(parse(pron))
        except ValueError:
            continue
    return entries


@cache
def cmudict() -> Lexicon:
    data = resources.files("retake.languages").joinpath("cmudict.dict.gz").read_bytes()
    text = gzip.decompress(data).decode("utf-8")
    return Lexicon(parse_dict(text.splitlines()))
