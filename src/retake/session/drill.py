from __future__ import annotations

from dataclasses import dataclass, field

from .takes import Take

PASSED = "passed"
SKIPPED = "skipped"
UNCOACHED = "uncoached"

# How long to wait for the reference voice before listening anyway (TTS can fail or be slow).
VOICE_TIMEOUT = 4.0
# A drill asked for (D, "retake, drill it") runs even with the automatic drill off, this many times.
ON_DEMAND_TIMES = 3
SHORTEST_ATTEMPT = 0.2
# A try this long may be a voice command ("retake, skip it") rather than the word; its score waits
# this long for the command to show up before it counts.
LONG_ATTEMPT = 0.9
COMMAND_WINDOW = 0.6


@dataclass
class DrillWord:
    index: int
    text: str
    key: str
    override: str | None
    entry: dict


@dataclass
class Drill:
    """Practice for the words that sank a take: hear the word, say it so many times in a row, then
    read the sentence again from the start.

    Nothing is heard while the reference voice plays: listening starts once it (and its echo) is
    over, with a cue. Each attempt is one stretch of speech that begins after the cue; it's scored as
    that word alone."""

    take: Take
    words: list[DrillWord]
    times: int
    position: int = 0
    passes: int = 0
    attempts: int = 0
    last_score: float | None = None
    listen_at: float | None = None
    listen_from: float | None = None
    voice_deadline: float = 0.0
    speech_start: float | None = None
    early: bool = False
    scoring: bool = False
    attempt: tuple[float, float] | None = None
    held: tuple[float | None, float] | None = None
    outcomes: list[dict] = field(default_factory=list)

    @property
    def word(self) -> DrillWord:
        return self.words[self.position]

    @property
    def done(self) -> bool:
        return self.position >= len(self.words)

    def saying(self, now: float) -> None:
        """The reference voice is about to play; nothing heard until it ends counts."""
        self.listen_at = None
        self.listen_from = None
        self.voice_deadline = now + VOICE_TIMEOUT
        self.speech_start = None

    def voice_ended(self, end: float) -> None:
        self.listen_at = end

    def listen(self, time: float) -> bool:
        """Starts listening once the voice is over, or never came; True when it just did."""
        if self.listen_from is not None or time < (self.voice_deadline if self.listen_at is None else self.listen_at):
            return False
        self.listen_from = time
        self.speech_start = None
        return True

    def on_vad(self, speech: bool, time: float) -> tuple[float, float] | None:
        """Returns the stretch to score when an attempt ends. Speech that began before the cue is
        no attempt: it holds the voice's echo, or a word with its start cut off."""
        self.early = False
        if self.listen_from is None or self.scoring:
            return None
        if speech:
            self.speech_start = time if time >= self.listen_from else None
            return None
        start, self.speech_start = self.speech_start, None
        if start is None:
            self.early = time > self.listen_from + SHORTEST_ATTEMPT
            return None
        if time - start < SHORTEST_ATTEMPT:
            return None
        return start, time

    def scored(self, score: float | None, threshold: float) -> bool:
        self.scoring = False
        self.attempts += 1
        self.last_score = score
        passed = score is not None and score >= threshold
        self.passes = self.passes + 1 if passed else 0
        return passed

    def finish_word(self, outcome: str) -> None:
        word = self.word
        word.entry["drill"] = outcome
        word.entry["drill_attempts"] = self.attempts
        self.outcomes.append({"word": word.index, "key": word.key, "outcome": outcome, "attempts": self.attempts})
        self.position += 1
        self.passes = 0
        self.attempts = 0
        self.last_score = None
        self.scoring = False
        self.attempt = None
        self.held = None

    def as_dict(self) -> dict:
        if self.done:
            return {}
        word = self.word
        return {
            "active": True,
            "word": word.index,
            "text": word.text,
            "expected": word.entry.get("expected", ""),
            "heard": word.entry.get("heard", ""),
            "patterns": word.entry.get("patterns", []),
            "times": self.times,
            "passes": self.passes,
            "attempts": self.attempts,
            "lastScore": -1 if self.last_score is None else round(self.last_score),
            "listening": self.listen_from is not None,
            "remaining": len(self.words) - self.position - 1,
        }
