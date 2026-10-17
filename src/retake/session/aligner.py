from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from rapidfuzz.distance import Levenshtein
from rapidfuzz.fuzz import ratio

from ..phonetics.cmudict import cmudict

MATCH_THRESHOLD = 0.72
MAX_SPAN = 4
SKIP_WORD = -0.55
INSERT_TOKEN = -0.35


@dataclass(frozen=True)
class HypToken:
    text: str
    start: float
    end: float
    conf: float = 1.0


@dataclass(frozen=True)
class Match:
    word: int
    first_token: int
    last_token: int
    similarity: float


@dataclass
class Alignment:
    matches: list[Match]
    inserted: list[int]
    skipped: list[int]
    score: float

    @property
    def last_word(self) -> int:
        return self.matches[-1].word if self.matches else -1


@lru_cache(maxsize=65536)
def _phonetic(text: str) -> str:
    dictionary = cmudict()
    pieces = []
    for token in text.split():
        phones = dictionary.first(token)
        if phones is None:
            return ""
        pieces.extend(p.symbol for p in phones)
    return " ".join(pieces)


@lru_cache(maxsize=65536)
def similarity(variant: str, spoken: str) -> float:
    a = variant.replace(" ", "")
    b = spoken.replace(" ", "")
    if a == b:
        return 1.0
    score = ratio(a, b) / 100.0
    pa, pb = _phonetic(variant), _phonetic(spoken)
    if pa and pb:
        phonetic = 1.0 - Levenshtein.normalized_distance(pa.split(), pb.split())
        score = max(score, phonetic)
    return score


def word_similarity(variants: list[list[str]], tokens: list[str]) -> float:
    spoken = " ".join(tokens)
    return max((similarity(" ".join(v), spoken) for v in variants), default=0.0)


def align(
    word_variants: list[list[list[str]]],
    tokens: list[str],
    anchored: bool = True,
) -> Alignment:
    n, m = len(word_variants), len(tokens)
    neg = float("-inf")
    score = [[neg] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple[int, int, str, float] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    score[0][0] = 0.0
    for j in range(1, m + 1):
        score[0][j] = score[0][j - 1] + INSERT_TOKEN
        back[0][j] = (0, j - 1, "insert", 0.0)
    for i in range(1, n + 1):
        score[i][0] = score[i - 1][0] + SKIP_WORD
        back[i][0] = (i - 1, 0, "skip", 0.0)
    for i in range(1, n + 1):
        variants = word_variants[i - 1]
        for j in range(0, m + 1):
            best = score[i][j]
            pointer = back[i][j]
            if j > 0:
                candidate = score[i][j - 1] + INSERT_TOKEN
                if candidate > best:
                    best, pointer = candidate, (i, j - 1, "insert", 0.0)
            candidate = score[i - 1][j] + SKIP_WORD
            if candidate > best:
                best, pointer = candidate, (i - 1, j, "skip", 0.0)
            for span in range(1, min(MAX_SPAN, j) + 1):
                sim = word_similarity(variants, tokens[j - span:j])
                if sim < MATCH_THRESHOLD:
                    continue
                gain = (sim - MATCH_THRESHOLD) / (1 - MATCH_THRESHOLD) + 0.5
                if span > 1:
                    gain -= 0.05 * (span - 1)
                candidate = score[i - 1][j - span] + gain
                if candidate > best:
                    best, pointer = candidate, (i - 1, j - span, "match", sim)
            score[i][j] = best
            back[i][j] = pointer
    if anchored:
        end_i = max(range(n + 1), key=lambda i: (score[i][m], i))
    else:
        end_i = n
    matches: list[Match] = []
    inserted: list[int] = []
    skipped: list[int] = []
    i, j = end_i, m
    while i > 0 or j > 0:
        pointer = back[i][j]
        if pointer is None:
            break
        pi, pj, kind, sim = pointer
        if kind == "match":
            matches.append(Match(i - 1, pj, j - 1, sim))
        elif kind == "insert":
            inserted.append(j - 1)
        else:
            skipped.append(i - 1)
        i, j = pi, pj
    matches.reverse()
    inserted.reverse()
    skipped.reverse()
    last = matches[-1].word if matches else -1
    skipped = [s for s in skipped if s < last]
    return Alignment(matches, inserted, skipped, score[end_i][m])
