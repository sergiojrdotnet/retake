from __future__ import annotations

from dataclasses import dataclass

VOWELS = frozenset(
    "AA AE AH AO AW AY EH ER EY IH IY OW OY UH UW".split()
)
CONSONANTS = frozenset(
    "B CH D DH F G HH JH K L M N NG P R S SH T TH V W Y Z ZH".split()
)

PRIMARY = 1
SECONDARY = 2
UNSTRESSED = 0


@dataclass(frozen=True, slots=True)
class Phone:
    symbol: str
    stress: int | None = None

    @property
    def is_vowel(self) -> bool:
        return self.symbol in VOWELS

    def __str__(self) -> str:
        return f"{self.symbol}{self.stress}" if self.stress is not None else self.symbol


def parse(arpabet: str) -> list[Phone]:
    phones = []
    for token in arpabet.split():
        symbol = token.rstrip("012")
        digits = token[len(symbol):]
        stress = int(digits) if digits else (UNSTRESSED if symbol in VOWELS else None)
        if symbol not in VOWELS and symbol not in CONSONANTS:
            raise ValueError(f"unknown ARPAbet symbol: {token}")
        phones.append(Phone(symbol, stress if symbol in VOWELS else None))
    return phones


IPA_VOWELS = {
    "AA": "ɑ", "AE": "æ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ", "EH": "ɛ",
    "EY": "eɪ", "IH": "ɪ", "IY": "i", "OW": "oʊ", "OY": "ɔɪ", "UH": "ʊ", "UW": "u",
}
IPA_CONSONANTS = {
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ", "HH": "h",
    "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ", "P": "p",
    "R": "r", "S": "s", "SH": "ʃ", "T": "t", "TH": "θ", "V": "v", "W": "w",
    "Y": "j", "Z": "z", "ZH": "ʒ",
}


def phone_to_ipa(phone: Phone) -> str:
    if phone.symbol == "AH":
        return "ʌ" if phone.stress else "ə"
    if phone.symbol == "ER":
        return "ɝ" if phone.stress else "ɚ"
    if phone.is_vowel:
        return IPA_VOWELS[phone.symbol]
    return IPA_CONSONANTS[phone.symbol]
