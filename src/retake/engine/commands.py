from __future__ import annotations

import re
import threading

from ..languages.packs import COMMAND_ACTIONS, LanguagePack

_PUNCTUATION = re.compile(r"[^\w'\s-]")


def _tokens(text: str) -> list[str]:
    return _PUNCTUATION.sub("", text.lower().replace("’", "'")).replace("-", " ").split()


class TranscriptCommands:
    """Finds voice commands in the tracking transcript.

    Whisper understands accented speech far better than the small command model, so when it
    writes "he'd take again" this catches the command the grammar-based recognizer missed."""

    def __init__(self, pack: LanguagePack, wake: str, aliases: list[str] | None = None):
        wakes = [wake.lower().strip()] + [a for a in (aliases or []) if a != wake]
        sequences = []
        for prefix in wakes:
            for action in COMMAND_ACTIONS:
                for alternative in pack.commands.get(action, ()):
                    sequences.append((tuple(_tokens(f"{prefix} {alternative}")), action, False))
            for say in pack.say_prefixes:
                sequences.append((tuple(_tokens(f"{prefix} {say}")), "say", True))
        self.sequences = sorted(sequences, key=lambda item: -len(item[0]))

    def find(self, words: list[dict]) -> list[dict]:
        flat = [(token, index) for index, word in enumerate(words) for token in _tokens(word["text"])]
        events = []
        position = 0
        while position < len(flat):
            found = None
            for sequence, action, takes_word in self.sequences:
                size = len(sequence)
                if tuple(token for token, _ in flat[position:position + size]) != sequence:
                    continue
                last = position + size - 1
                arg = None
                if takes_word:
                    if position + size >= len(flat):
                        continue
                    last += 1
                    arg = flat[last][0]
                found = (action, arg, last, " ".join(sequence + ((arg,) if arg else ())))
                break
            if found is None:
                position += 1
                continue
            action, arg, last, phrase = found
            first_word, last_word = words[flat[position][1]], words[flat[last][1]]
            span = words[flat[position][1]:flat[last][1] + 1]
            events.append({
                "type": "command",
                "action": action,
                "arg": arg,
                "phrase": phrase,
                "start": first_word["start"],
                "end": last_word["end"],
                "confidence": min(w.get("conf", 1.0) for w in span),
                "source": "transcript",
            })
            position = last + 1
        return events


class CommandGate:
    """Lets each spoken command through once, whichever recognizer reports it first."""

    def __init__(self, window: float = 2.0):
        self.window = window
        self.lock = threading.Lock()
        self.recent: list[tuple[str, float]] = []

    def admit(self, event: dict) -> bool:
        with self.lock:
            start = event["start"]
            if any(action == event["action"] and abs(seen - start) < self.window for action, seen in self.recent):
                return False
            self.recent = [(a, s) for a, s in self.recent if start - s < 60] + [(event["action"], start)]
            return True
