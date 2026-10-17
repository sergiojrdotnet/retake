from __future__ import annotations

from dataclasses import asdict, dataclass

from ..languages.packs import LanguagePack
from ..phonetics.guides import GuideBook
from ..script.model import CAMERA, SCENE, Script

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
    video_backend: str,
    obs_scenes: list[str] | None = None,
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
    scenes = set(obs_scenes or [])
    for sentence in script.sentences:
        for token in sentence.tokens:
            if token.kind == SCENE:
                if video_backend != "obs":
                    issues.append(Issue(INFO, "cue", f"(SCENE: {token.value}) needs the OBS backend; it will be ignored", sentence=sentence.index))
                elif obs_scenes is not None and token.value not in scenes:
                    issues.append(Issue(WARNING, "cue", f"OBS has no scene named “{token.value}”", sentence=sentence.index))
            elif token.kind == CAMERA:
                if token.value not in ("full", "corner", "small", "off"):
                    issues.append(Issue(WARNING, "cue", f"(CAMERA: {token.value}) is not a layout (use full, corner or off)", sentence=sentence.index))
                elif video_backend not in ("builtin",):
                    issues.append(Issue(INFO, "cue", f"(CAMERA: {token.value}) only applies to screen recording with the built-in recorder", sentence=sentence.index))
    order = {ERROR: 0, WARNING: 1, INFO: 2}
    return sorted(issues, key=lambda issue: (order[issue.severity], issue.sentence))
