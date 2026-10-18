from __future__ import annotations

from dataclasses import asdict, dataclass

from ..languages.packs import LanguagePack
from ..phonetics.guides import GuideBook
from ..script.model import Script

ERROR = "error"
WARNING = "warning"
INFO = "info"


@dataclass
class Issue:
    severity: str
    kind: str
    message: str
    word: str = ""
    sentence: int = -1

    def as_dict(self) -> dict:
        return asdict(self)


def check(
    script: Script,
    guides: GuideBook,
    pack: LanguagePack,
    wake_word: str,
    missing_models: list[str] | None = None,
    engine_errors: dict[str, str] | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    for model in missing_models or []:
        issues.append(Issue(ERROR, "model", f"Model not installed: {model}"))
    for role, error in (engine_errors or {}).items():
        issues.append(Issue(ERROR, "engine", f"{role}: {error}"))
    seen: set[str] = set()
    for word in script.words:
        key = word.key
        if not key or key in seen or word.override_ipa:
            continue
        seen.add(key)
        guide = guides.for_word(word)
        shown = word.display.strip(".,;:!?\"'()[]")
        if guide is None or guide.source == "none":
            issues.append(Issue(WARNING, "pronunciation", f"No pronunciation for “{shown}”; add {{{key}|IPA}} or a lexicon entry", key, word.sentence))
        elif guide.source == "espeak":
            issues.append(Issue(INFO, "pronunciation", f"“{shown}” is not in the dictionary; guessed {guide.ipa}", key, word.sentence))
        elif guide.heteronym and guide.source != "lexicon":
            issues.append(Issue(INFO, "heteronym", f"“{shown}” has more than one pronunciation; showing {guide.ipa}", key, word.sentence))
    wake = wake_word.lower().strip()
    if wake:
        for sentence in script.sentences:
            if any(w.key == wake for w in sentence.words):
                issues.append(Issue(WARNING, "wake-word", f"The wake word “{wake_word}” appears in the script; voice commands may trigger while reading", wake, sentence.index))
                break
    order = {ERROR: 0, WARNING: 1, INFO: 2}
    return sorted(issues, key=lambda issue: (order[issue.severity], issue.sentence))
