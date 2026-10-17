from __future__ import annotations

from .arpabet import Phone

ONSETS = frozenset(
    tuple(onset.split())
    for onset in (
        "P R", "P L", "B R", "B L", "T R", "D R", "K R", "K L", "G R", "G L",
        "F R", "F L", "TH R", "SH R", "S P", "S T", "S K", "S M", "S N", "S L",
        "S W", "S F", "T W", "D W", "K W", "G W", "TH W", "P Y", "B Y", "F Y",
        "V Y", "M Y", "K Y", "HH Y", "G Y", "L Y", "N Y",
        "S P R", "S P L", "S T R", "S K R", "S K W", "S P Y", "S K Y",
    )
)


CHECKED = frozenset({"IH", "EH", "AE", "UH", "AH"})


def _legal_onset(cluster: tuple[str, ...]) -> bool:
    if not cluster:
        return True
    if len(cluster) == 1:
        return cluster[0] != "NG"
    return cluster in ONSETS


def syllabify(phones: list[Phone]) -> list[list[Phone]]:
    nuclei = [i for i, p in enumerate(phones) if p.is_vowel]
    if not nuclei:
        return [list(phones)] if phones else []
    boundaries = [0]
    for left, right in zip(nuclei, nuclei[1:]):
        cluster = tuple(p.symbol for p in phones[left + 1:right])
        split = len(cluster)
        for start in range(len(cluster) + 1):
            if _legal_onset(cluster[start:]):
                split = start
                break
        nucleus = phones[left]
        if split == 0 and cluster and nucleus.symbol in CHECKED and nucleus.stress:
            split = 1
        boundaries.append(left + 1 + split)
    boundaries.append(len(phones))
    return [phones[a:b] for a, b in zip(boundaries, boundaries[1:]) if a < b]


def count(phones: list[Phone]) -> int:
    return sum(1 for p in phones if p.is_vowel)
