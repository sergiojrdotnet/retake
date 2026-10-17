from __future__ import annotations

from .arpabet import PRIMARY, SECONDARY, UNSTRESSED, Phone

_TOKENS: dict[str, tuple[str, ...]] = {
    "aɪ": ("AY",), "aʊ": ("AW",), "eɪ": ("EY",), "oʊ": ("OW",), "əʊ": ("OW",),
    "ɔɪ": ("OY",), "ɪə": ("IH", "R"), "eə": ("EH", "R"), "ʊə": ("UH", "R"),
    "iː": ("IY",), "uː": ("UW",), "ɑː": ("AA",), "ɔː": ("AO",), "ɜː": ("ER",),
    "oː": ("OW",), "eː": ("EY",),
    "i": ("IY",), "ɪ": ("IH",), "ᵻ": ("IH",), "e": ("EY",), "ɛ": ("EH",),
    "æ": ("AE",), "a": ("AA",), "ɑ": ("AA",), "ɒ": ("AA",), "ɔ": ("AO",),
    "o": ("OW",), "ʊ": ("UH",), "u": ("UW",), "ʌ": ("AH",), "ə": ("AH",),
    "ɐ": ("AH",), "ɚ": ("ER",), "ɝ": ("ER",), "ɜ": ("ER",),
    "l̩": ("AH", "L"), "n̩": ("AH", "N"), "m̩": ("AH", "M"), "əl": ("AH", "L"),
    "tʃ": ("CH",), "dʒ": ("JH",), "ʧ": ("CH",), "ʤ": ("JH",),
    "p": ("P",), "b": ("B",), "t": ("T",), "d": ("D",), "k": ("K",),
    "ɡ": ("G",), "g": ("G",), "f": ("F",), "v": ("V",), "θ": ("TH",),
    "ð": ("DH",), "s": ("S",), "z": ("Z",), "ʃ": ("SH",), "ʒ": ("ZH",),
    "h": ("HH",), "ç": ("HH",), "x": ("HH",), "m": ("M",), "n": ("N",),
    "ŋ": ("NG",), "l": ("L",), "ɫ": ("L",), "ɹ": ("R",), "r": ("R",),
    "ɻ": ("R",), "w": ("W",), "ʍ": ("W",), "j": ("Y",), "ɾ": ("T",),
    "ʔ": ("T",),
}
_MAX_TOKEN = max(len(t) for t in _TOKENS)
_IGNORED = set(" .ˑ/[]()ʰ̃ʲ̪‿-|")
_STRIP = {"‍": "", "͡": "", "͜": "", "'": "ˈ", ",": "ˌ"}
_REDUCED = {"ə", "ɐ", "ᵻ", "ɚ"}


def normalize(ipa: str) -> str:
    for old, new in _STRIP.items():
        ipa = ipa.replace(old, new)
    return ipa


def to_phones(ipa: str) -> list[Phone]:
    text = normalize(ipa)
    phones: list[Phone] = []
    reduced: list[bool] = []
    pending_stress: int | None = None
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "ˈ":
            pending_stress = PRIMARY
            i += 1
            continue
        if ch == "ˌ":
            pending_stress = SECONDARY
            i += 1
            continue
        if ch in _IGNORED or ch == "ː":
            i += 1
            continue
        for size in range(min(_MAX_TOKEN, len(text) - i), 0, -1):
            chunk = text[i:i + size]
            if chunk in _TOKENS:
                for symbol in _TOKENS[chunk]:
                    phone = Phone(symbol)
                    if phone.is_vowel:
                        stress = pending_stress if pending_stress is not None else UNSTRESSED
                        pending_stress = None
                        phone = Phone(symbol, stress)
                        reduced.append(chunk in _REDUCED or chunk.startswith("ə"))
                    else:
                        reduced.append(False)
                    phones.append(phone)
                i += size
                break
        else:
            i += 1
    return _ensure_primary(phones, reduced)


def _ensure_primary(phones: list[Phone], reduced: list[bool]) -> list[Phone]:
    if any(p.is_vowel and p.stress == PRIMARY for p in phones):
        return phones
    for index, phone in enumerate(phones):
        if phone.is_vowel and not reduced[index]:
            phones[index] = Phone(phone.symbol, PRIMARY)
            return phones
    for index, phone in enumerate(phones):
        if phone.is_vowel:
            phones[index] = Phone(phone.symbol, PRIMARY)
            return phones
    return phones


def possessive_suffix(ipa: str) -> str:
    ending = ipa.rstrip("ˈˌː/ ")
    if ending.endswith(("s", "z", "ʃ", "ʒ", "tʃ", "dʒ")):
        return "ɪz"
    return "s" if ending[-1:] in ("p", "t", "k", "f", "θ") else "z"
