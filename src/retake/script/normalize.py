from __future__ import annotations

import re
import unicodedata

_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_SCALES = ((1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand"))
_ORDINALS = {
    "one": "first", "two": "second", "three": "third", "five": "fifth",
    "eight": "eighth", "nine": "ninth", "twelve": "twelfth",
}

_PUNCT = re.compile(r"[^\w'%.\-]+", re.UNICODE)
_NUMBER = re.compile(r"^(\d+(?:[.,]\d+)?)(%|st|nd|rd|th|k|m)?$")
_MIXED = re.compile(r"^([a-z]+)(\d+)$")


def cardinal(n: int) -> list[str]:
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        tens, ones = divmod(n, 10)
        return [_TENS[tens]] + ([_ONES[ones]] if ones else [])
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return [_ONES[hundreds], "hundred"] + (cardinal(rest) if rest else [])
    for scale, name in _SCALES:
        if n >= scale:
            head, rest = divmod(n, scale)
            return cardinal(head) + [name] + (cardinal(rest) if rest else [])
    return [str(n)]


def year(n: int) -> list[str] | None:
    if not 1100 <= n <= 2099:
        return None
    if 2000 <= n <= 2009:
        return ["two", "thousand"] + ([_ONES[n - 2000]] if n > 2000 else [])
    head, tail = divmod(n, 100)
    if tail == 0:
        return cardinal(head) + ["hundred"]
    if tail < 10:
        return cardinal(head) + ["oh", _ONES[tail]]
    return cardinal(head) + cardinal(tail)


def ordinal(n: int) -> list[str]:
    words = cardinal(n)
    last = words[-1]
    if last in _ORDINALS:
        words[-1] = _ORDINALS[last]
    elif last.endswith("y"):
        words[-1] = last[:-1] + "ieth"
    else:
        words[-1] = last + "th"
    return words


def number_variants(token: str) -> list[list[str]]:
    match = _NUMBER.match(token.lower())
    if not match:
        return []
    number, suffix = match.groups()
    if "." in number or "," in number:
        separator = "." if "." in number else ","
        whole, fraction = number.split(separator, 1)
        if separator == "," and len(fraction) == 3:
            return [cardinal(int(whole + fraction))]
        words = cardinal(int(whole)) + ["point"] + [_ONES[int(d)] for d in fraction]
        return [words + (["percent"] if suffix == "%" else [])]
    value = int(number)
    if suffix == "%":
        return [cardinal(value) + ["percent"]]
    if suffix in ("st", "nd", "rd", "th"):
        return [ordinal(value)]
    if suffix == "k":
        return [cardinal(value) + ["k"], cardinal(value) + ["thousand"]]
    if suffix == "m":
        return [cardinal(value) + ["m"], cardinal(value) + ["million"]]
    variants = [cardinal(value)]
    as_year = year(value) if len(number) == 4 else None
    if as_year and as_year != variants[0]:
        variants.insert(0, as_year)
    if len(number) > 1 and number.startswith("0"):
        variants.append([_ONES[int(d)] for d in number])
    return variants


CURRENCY = re.compile(r"^(?:US\$|R\$|A\$|C\$|\$|€|£|¥)$", re.IGNORECASE)
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")


def clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return _THOUSANDS.sub("", text)


def simple_tokens(text: str) -> list[str]:
    text = clean(text).lower()
    tokens = []
    for raw in _PUNCT.sub(" ", text).split():
        raw = raw.strip("'.-")
        if not raw:
            continue
        if _NUMBER.match(raw):
            tokens.append(raw)
            continue
        tokens.extend(part for part in re.split(r"[-.]", raw) if part)
    return tokens


def word_variants(display: str, numbers: str | None = "en", spoken: dict[str, list[list[str]]] | None = None) -> list[list[str]]:
    original = clean(display).strip()
    tokens = simple_tokens(original)
    if not tokens:
        return []
    variants: list[list[str]] = []
    expanded: list[list[str]] = [[]]
    for token in tokens:
        options = list(spoken.get(token, [])) if spoken else []
        if spoken and not options and token.endswith("'s") and token[:-2] in spoken:
            for alternative in spoken[token[:-2]]:
                options.append(alternative[:-1] + [alternative[-1] + "'s"])
                options.append(alternative + ["s"])
        numeric = number_variants(token) if numbers == "en" else []
        options += numeric
        mixed = _MIXED.match(token) if numbers == "en" else None
        if mixed and not numeric:
            letters, digits = mixed.groups()
            options.append((list(letters) if len(letters) <= 3 else [letters]) + cardinal(int(digits)))
        if not numeric:
            options.append([token])
        expanded = [prefix + option for prefix in expanded for option in options][:4]
    variants.extend(expanded)
    letters = re.sub(r"[^A-Za-z]", "", original)
    if letters.isupper() and 2 <= len(letters) <= 6:
        variants.append([c.lower() for c in letters])
    if original.endswith("'s") and len(tokens) == 1:
        variants.append([tokens[0].removesuffix("'s"), "s"])
    unique: list[list[str]] = []
    for v in variants:
        if v not in unique:
            unique.append(v)
    return unique


def hypothesis_tokens(text: str, numbers: str | None = "en") -> list[str]:
    tokens: list[str] = []
    for token in simple_tokens(text):
        options = number_variants(token) if numbers == "en" else []
        tokens.extend(options[0] if options else [token])
    return tokens
