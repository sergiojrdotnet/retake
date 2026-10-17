from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz.distance import Levenshtein

from ..languages.packs import L1Error, LanguagePack
from ..phonetics import ipa as ipa_parser
from ..phonetics.arpabet import VOWELS
from ..script.lexicon import atomic_write

WARN = "warn"
REQUIRE = "require"
LOG = "log"


@dataclass
class CoachSettings:
    """Two levels: a word under `threshold` is shown in the coach panel; under `require` (when set) it
    sinks the take, and with `drill` on it's practised right away before the sentence is read again."""

    enabled: bool = True
    threshold: float = 55.0
    require: float | None = None
    drill: bool = True
    drill_times: int = 3
    timing: str = "live"
    auto_flag_misses: int = 3


def detect_patterns(expected_ipa: str, heard_ipa: str, catalog: tuple[L1Error, ...]) -> list[L1Error]:
    expected = [p.symbol for p in ipa_parser.to_phones(expected_ipa)]
    heard = [p.symbol for p in ipa_parser.to_phones(heard_ipa)]
    if not expected or not heard or expected == heard:
        return []
    found: list[L1Error] = []
    ops = Levenshtein.editops(expected, heard)
    last_consonant = max((i for i, s in enumerate(expected) if s not in VOWELS), default=-1)
    for op in ops:
        for error in catalog:
            if error in found:
                continue
            if op.tag == "replace" and error.expected and error.heard:
                want, got = expected[op.src_pos], heard[op.dest_pos]
                if want in error.expected and got in error.heard and want != got:
                    if error.position == "initial" and op.src_pos != 0:
                        continue
                    if error.position == "final" and op.src_pos != len(expected) - 1:
                        continue
                    found.append(error)
            elif op.tag == "insert" and error.extra:
                got = heard[op.dest_pos]
                if got not in error.extra:
                    continue
                if error.before_final:
                    if op.src_pos == len(expected) - 1 and expected[-1] in error.before_final:
                        found.append(error)
                elif op.src_pos >= len(expected) or op.src_pos == 0 or op.src_pos > last_consonant:
                    found.append(error)
            elif op.tag == "delete" and error.missing:
                want = expected[op.src_pos]
                if want in error.expected and (error.position != "final" or op.src_pos == len(expected) - 1):
                    found.append(error)
    return found


@dataclass
class PracticeHistory:
    path: Path | None
    words: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> PracticeHistory:
        history = cls(path)
        if path.exists():
            try:
                history.words = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                history.words = {}
        return history

    def record(self, key: str, missed: bool) -> dict:
        entry = self.words.setdefault(key, {"attempts": 0, "misses": 0, "flagged": False})
        entry["attempts"] += 1
        entry["misses"] += int(missed)
        entry["last"] = time.time()
        return entry

    def should_flag(self, key: str, misses: int) -> bool:
        entry = self.words.get(key)
        if not entry or entry.get("flagged"):
            return False
        return entry["misses"] >= misses and entry["misses"] / max(1, entry["attempts"]) >= 0.5

    def flag(self, key: str, flagged: bool = True) -> None:
        self.words.setdefault(key, {"attempts": 0, "misses": 0})["flagged"] = flagged

    def flagged(self) -> set[str]:
        return {k for k, v in self.words.items() if v.get("flagged")}

    def set_coached(self, key: str, coached: bool) -> None:
        """Names and words you never want scored, drilled or given guides for, in any project."""
        entry = self.words.setdefault(key, {"attempts": 0, "misses": 0})
        if coached:
            entry.pop("uncoached", None)
        else:
            entry["uncoached"] = True

    def uncoached(self) -> set[str]:
        return {k for k, v in self.words.items() if v.get("uncoached")}

    def drill_list(self) -> list[tuple[str, int, int]]:
        rows = [(k, v["misses"], v["attempts"]) for k, v in self.words.items() if v.get("misses")]
        return sorted(rows, key=lambda r: (-r[1], r[0]))

    def save(self) -> None:
        if self.path:
            atomic_write(self.path, json.dumps(self.words, indent=1, ensure_ascii=False))


def flag_entry(word: dict, threshold: float, native: LanguagePack | None) -> dict | None:
    score = word.get("score")
    if score is None or score >= threshold:
        return None
    patterns = detect_patterns(word.get("expected", ""), word.get("heard", ""), native.l1_errors if native else ())
    return {
        **word,
        "patterns": [{"id": p.id, "title": p.title, "description": p.description} for p in patterns],
    }
