from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..languages.packs import COMMAND_ACTIONS, LanguagePack
from .audio import RATE

_models: dict[str, object] = {}


def load_model(directory: Path):
    from vosk import Model, SetLogLevel

    SetLogLevel(-1)
    key = str(directory)
    if key not in _models:
        _models[key] = Model(key)
    return _models[key]


def _words(result: dict, offset: float, key: str) -> list[dict]:
    words = []
    for item in result.get(key, []):
        words.append({
            "text": item["word"],
            "start": offset + item["start"],
            "end": offset + item["end"],
            "conf": item.get("conf", 1.0),
        })
    return words


class VoskTracker:
    name = "vosk"

    def __init__(self, model_dir: Path):
        self.model = load_model(model_dir)
        self.recognizer = None
        self.offset = 0.0
        self.last_partial: list[str] = []
        self.since_partial = 0

    def reset(self, start_sample: int) -> None:
        from vosk import KaldiRecognizer

        self.recognizer = KaldiRecognizer(self.model, RATE)
        self.recognizer.SetWords(True)
        self.recognizer.SetPartialWords(True)
        self.offset = start_sample / RATE
        self.last_partial = []

    def feed(self, start_sample: int, samples: np.ndarray) -> list[dict]:
        if self.recognizer is None:
            self.reset(start_sample)
        events = []
        if self.recognizer.AcceptWaveform(samples.tobytes()):
            result = json.loads(self.recognizer.Result())
            words = _words(result, self.offset, "result")
            self.last_partial = []
            if words:
                events.append({"type": "words", "final": True, "words": words})
        else:
            self.since_partial += len(samples)
            if self.since_partial < RATE * 0.15:
                return events
            self.since_partial = 0
            partial = json.loads(self.recognizer.PartialResult())
            words = _words(partial, self.offset, "partial_result")
            texts = [w["text"] for w in words]
            if texts != self.last_partial:
                self.last_partial = texts
                events.append({"type": "words", "final": False, "words": words})
        return events


class VoskCommands:
    name = "vosk-commands"

    def __init__(self, model_dir: Path, pack: LanguagePack, wake_word: str | None = None, min_confidence: float = 0.6, aliases: list[str] | None = None):
        self.model = load_model(model_dir)
        self.pack = pack
        self.wake = (wake_word or pack.wake_word).lower().strip()
        self.aliases = [a for a in (aliases or []) if a != self.wake]
        self.min_confidence = min_confidence
        self.recognizer = None
        self.offset = 0.0
        self.phrases: dict[str, tuple[str, str | None]] = {}
        self.missing: list[str] = []
        self.words: list[str] = []
        self.start_sample = 0
        self._build()

    def known(self, word: str) -> bool:
        return all(self.model.vosk_model_find_word(part) >= 0 for part in word.split())

    def set_words(self, words: list[str]) -> None:
        cleaned = sorted({w.lower() for w in words if w and w.replace("'", "").isalpha()})
        if cleaned != self.words:
            self.words = cleaned
            self._build()
            self._recreate()

    def _build(self) -> None:
        phrases: dict[str, tuple[str, str | None]] = {}
        missing = []
        if not self.known(self.wake):
            missing.append(self.wake)
        wakes = [self.wake] + [a for a in self.aliases if self.known(a)]
        for action in COMMAND_ACTIONS:
            for alternative in self.pack.commands.get(action, ()):
                if not self.known(alternative.lower()):
                    missing.append(alternative)
                    continue
                for wake in wakes:
                    phrases[f"{wake} {alternative.lower()}"] = (action, None)
        for prefix in self.pack.say_prefixes:
            for word in self.words:
                for wake in wakes:
                    phrase = f"{wake} {prefix.lower()} {word}"
                    if self.known(phrase):
                        phrases[phrase] = ("say", word)
        self.phrases = phrases
        self.missing = missing

    def _recreate(self) -> None:
        from vosk import KaldiRecognizer

        if self.recognizer is not None:
            self.start_sample = getattr(self, "audio_end", self.start_sample)

        grammar = json.dumps(list(self.phrases) + ["[unk]"], ensure_ascii=False)
        self.recognizer = KaldiRecognizer(self.model, RATE, grammar)
        self.recognizer.SetWords(True)
        self.offset = self.start_sample / RATE

    def reset(self, start_sample: int) -> None:
        self.start_sample = start_sample
        self._recreate()

    def feed(self, start_sample: int, samples: np.ndarray) -> list[dict]:
        if self.recognizer is None:
            self.reset(start_sample)
        self.start_sample = start_sample + len(samples)
        self.audio_end = self.start_sample
        if not self.recognizer.AcceptWaveform(samples.tobytes()):
            return []
        result = json.loads(self.recognizer.Result())
        words = result.get("result", [])
        tokens = [w["word"] for w in words]
        for size in range(min(len(tokens), 8), 1, -1):
            phrase = " ".join(tokens[-size:])
            if phrase not in self.phrases:
                continue
            tail = words[-size:]
            confidence = min(w.get("conf", 1.0) for w in tail)
            if confidence < self.min_confidence:
                return []
            action, arg = self.phrases[phrase]
            return [{
                "type": "command",
                "action": action,
                "arg": arg,
                "phrase": phrase,
                "start": self.offset + tail[0]["start"],
                "end": self.offset + tail[-1]["end"],
                "confidence": confidence,
            }]
        return []
