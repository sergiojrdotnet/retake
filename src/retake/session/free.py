from __future__ import annotations

import re
from typing import Protocol

from rapidfuzz.fuzz import ratio, token_set_ratio

from .aligner import HypToken
from .takes import COMPLETE, REJECTED, Take, TakeLog, WordTiming

PREROLL = 0.15
TAIL = 0.2
_END = re.compile(r"[.!?…]+[\"'”’)\]]*$")


class FreeEvents(Protocol):
    def take_started(self, take: Take) -> None: ...
    def take_completed(self, take: Take) -> None: ...
    def take_rejected(self, take: Take) -> None: ...
    def transcript_changed(self, partial: str) -> None: ...
    def off_script(self, start: float, end: float, text: str, inside: bool, filler: bool) -> None: ...


def is_retry(previous: str, current: str) -> bool:
    a, b = previous.lower().strip(), current.lower().strip()
    if not a or not b:
        return False
    first_a, first_b = a.split()[:3], b.split()[:3]
    if len(first_a) == 3 and first_a == first_b:
        return True
    length = len(b) / max(1, len(a))
    return token_set_ratio(a, b) >= 82 and ratio(a, b) >= 70 and 0.6 <= length <= 1.6


class FreeTracker:
    def __init__(self, log: TakeLog, events: FreeEvents, fillers: tuple[str, ...] = (), punctuated: bool = False):
        self.log = log
        self.events = events
        self.fillers = frozenset(fillers)
        self.punctuated = punctuated
        self.take: Take | None = None
        self.partial: list[HypToken] = []
        self.excluded: list[tuple[float, float]] = []
        self.floor = 0.0
        self.now = 0.0
        self.paused = False
        self.last_completed: Take | None = None
        self.targets: list[Take] = []

    def on_vad(self, speech: bool, time: float) -> None:
        self.now = max(self.now, time)

    def on_tick(self, time: float) -> None:
        self.now = max(self.now, time)

    def exclude(self, start: float, end: float) -> None:
        self.excluded.append((start, end))
        self.partial = [t for t in self.partial if not self._is_excluded(t)]

    def _is_excluded(self, token: HypToken) -> bool:
        middle = (token.start + token.end) / 2
        return any(a - 0.05 <= middle <= b + 0.05 for a, b in self.excluded)

    def on_words(self, tokens: list[HypToken], final: bool, replace_from: float | None = None) -> None:
        if self.paused:
            return
        tokens = [t for t in tokens if t.start >= self.floor - 1e-6 and not self._is_excluded(t)]
        if tokens:
            self.now = max(self.now, tokens[-1].end)
        if not final and replace_from is None:
            self.partial = tokens
            if tokens and self.take is None and not self._only_fillers(tokens):
                self.take = self.log.new_take(None, max(0.0, tokens[0].start - PREROLL))
                self.events.take_started(self.take)
            self.events.transcript_changed(" ".join(t.text for t in tokens))
            return
        self.partial = []
        self.events.transcript_changed("")
        if not tokens:
            return
        self.floor = tokens[-1].end
        if self._only_fillers(tokens):
            self.events.off_script(tokens[0].start, tokens[-1].end, " ".join(t.text for t in tokens), False, True)
            if self.take:
                self.log.takes.remove(self.take)
                self.take = None
            return
        for group in self._sentences(tokens):
            self._finish(group)

    def _only_fillers(self, tokens: list[HypToken]) -> bool:
        return all(t.text.lower().strip(".,!?") in self.fillers for t in tokens)

    def _sentences(self, tokens: list[HypToken]) -> list[list[HypToken]]:
        if not self.punctuated:
            return [tokens]
        groups, current = [], []
        for token in tokens:
            current.append(token)
            if _END.search(token.text):
                groups.append(current)
                current = []
        if current:
            groups.append(current)
        return groups

    def _finish(self, tokens: list[HypToken]) -> None:
        start = max(0.0, tokens[0].start - PREROLL)
        if self.take is None:
            self.take = self.log.new_take(None, start)
            self.events.take_started(self.take)
        take = self.take
        take.start = min(take.start, start)
        take.end = tokens[-1].end + TAIL
        take.text = " ".join(t.text for t in tokens)
        take.words = [WordTiming(-1, t.text, t.start, t.end) for t in tokens]
        take.status = COMPLETE
        self.take = None
        previous = self._retry_target(take)
        if previous is not None:
            previous.status = REJECTED
            previous.reason = "restart" if previous is self.last_completed else "pickup"
            self.events.take_rejected(previous)
            if previous in self.targets:
                self.targets.remove(previous)
        self.last_completed = take
        self.log.save()
        self.events.take_completed(take)

    def _retry_target(self, take: Take) -> Take | None:
        for target in self.targets:
            if target.status == COMPLETE and is_retry(target.text, take.text):
                return target
        previous = self.last_completed
        if previous and previous.status == COMPLETE and is_retry(previous.text, take.text):
            return previous
        return None

    def retake(self, reason: str = "command", end: float | None = None) -> Take | None:
        if self.take is not None:
            take = self.take
            take.end = end if end is not None else self.now
            take.status = REJECTED
            take.reason = reason
            take.text = " ".join(t.text for t in self.partial)
            self.take = None
            self.partial = []
            self.floor = take.end
            self.log.save()
            self.events.take_rejected(take)
            return take
        if self.last_completed and self.last_completed.status == COMPLETE:
            take = self.last_completed
            take.status = REJECTED
            take.reason = reason
            self.log.save()
            self.events.take_rejected(take)
            return take
        return None

    def stop(self) -> None:
        if self.take is not None:
            if self.partial and not self._only_fillers(self.partial):
                self._finish(self.partial)
            else:
                self.log.takes.remove(self.take)
                self.take = None
