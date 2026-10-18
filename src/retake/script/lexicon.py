from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass, field
from pathlib import Path

from ..phonetics.ipa import possessive_suffix


@dataclass
class Entry:
    ipa: str = ""
    flagged: bool = False
    spoken: str = ""
    coached: bool = True


@dataclass
class Lexicon:
    path: Path | None
    entries: dict[str, Entry] = field(default_factory=dict)

    @classmethod
    def for_script(cls, script_path: Path | None) -> Lexicon:
        if script_path is None:
            return cls(None)
        path = script_path.with_name(script_path.stem + ".lexicon.tsv")
        return cls.load(path)

    @classmethod
    def load(cls, path: Path) -> Lexicon:
        lexicon = cls(path)
        if path.exists():
            for row in csv.reader(io.StringIO(path.read_text(encoding="utf-8")), delimiter="\t"):
                if not row or row[0].startswith("#"):
                    continue
                word = row[0].strip().lower()
                ipa = row[1].strip() if len(row) > 1 else ""
                flagged = len(row) > 2 and row[2].strip().lower() in ("1", "yes", "true", "flagged")
                spoken = row[3].strip() if len(row) > 3 else ""
                coached = not (len(row) > 4 and row[4].strip().lower() in ("off", "no", "false", "0"))
                lexicon.entries[word] = Entry(ipa, flagged, spoken, coached)
        return lexicon

    def uncoached(self, key: str) -> bool:
        entry = self.entries.get(key)
        return entry is not None and not entry.coached

    def ipa(self, key: str) -> str | None:
        entry = self.entries.get(key)
        return entry.ipa if entry and entry.ipa else None

    def word_ipa(self, key: str) -> str | None:
        custom = self.ipa(key)
        if not custom and key.endswith("'s"):
            base = self.ipa(key[:-2])
            if base:
                custom = base + possessive_suffix(base)
        return custom

    def spoken_forms(self) -> dict[str, list[list[str]]]:
        forms: dict[str, list[list[str]]] = {}
        for word, entry in self.entries.items():
            if entry.spoken:
                forms[word] = [alternative.split() for alternative in entry.spoken.split("|") if alternative.strip()]
        return forms

    def is_flagged(self, key: str) -> bool:
        entry = self.entries.get(key)
        return bool(entry and entry.flagged)

    def set_flag(self, key: str, flagged: bool) -> None:
        entry = self.entries.setdefault(key, Entry())
        entry.flagged = flagged
        if not entry.flagged and not entry.ipa and not entry.spoken and entry.coached:
            del self.entries[key]
        self.save()

    def save(self) -> None:
        if self.path is None:
            return
        buffer = io.StringIO()
        buffer.write("# word\tipa\tflagged\tspoken\tcoach\n")
        writer = csv.writer(buffer, delimiter="\t", lineterminator="\n")
        for word in sorted(self.entries):
            entry = self.entries[word]
            writer.writerow([word, entry.ipa, "yes" if entry.flagged else "", entry.spoken, "" if entry.coached else "off"])
        atomic_write(self.path, buffer.getvalue())


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
