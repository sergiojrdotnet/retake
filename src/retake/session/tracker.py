from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..script.model import ADLIB, Script, Sentence, Token
from .aligner import Alignment, HypToken, align, word_similarity
from .takes import COMPLETE, REJECTED, Take, TakeLog, WordTiming

PREROLL = 0.15
TAIL = 0.2
COMPLETION_PAUSE = 0.35
SUBSTITUTION_SIMILARITY = 0.86
# A sentence's opening may arrive in pieces (a number read slowly, a pause after the first word):
# what was said within this window, with no longer pause in it, still counts toward the start.
START_WINDOW = 4.0
START_GAP = 1.5
# A start found at the second word reaches back to the token right before it when that token sounds
# like the first word: the opener was misheard, not skipped.
OPENER_GAP = 1.2
OPENER_SIMILARITY = 0.45
# Interim decodes end mid-phrase, and Whisper, prompted with the sentence, sometimes completes them
# with the sentence's last words. The reading position follows matches at most this many words
# apart; a longer jump counts once this many matched words in a row confirm it.
RUN_GAP = 2
JUMP_RUN = 3


class TrackerEvents(Protocol):
    def position_changed(self, sentence: int, word: int) -> None: ...
    def sentence_changed(self, sentence: int) -> None: ...
    def take_started(self, take: Take) -> None: ...
    def take_completed(self, take: Take) -> None: ...
    def take_rejected(self, take: Take) -> None: ...
    def cue_reached(self, token: Token, time: float) -> None: ...
    def off_script(self, start: float, end: float, text: str, inside: bool, filler: bool) -> None: ...


@dataclass
class _Stream:
    committed: list[HypToken] = field(default_factory=list)
    partial: list[HypToken] = field(default_factory=list)

    @property
    def tokens(self) -> list[HypToken]:
        return self.committed + self.partial

    def clear(self) -> None:
        self.committed.clear()
        self.partial.clear()

    def keep_from(self, start: float) -> None:
        self.committed = [t for t in self.committed if t.start >= start - 1e-6]
        self.partial = [t for t in self.partial if t.start >= start - 1e-6]


class ScriptTracker:
    def __init__(
        self,
        script: Script,
        log: TakeLog,
        events: TrackerEvents,
        fillers: tuple[str, ...] = (),
        function_words: frozenset[str] = frozenset(),
    ):
        self.script = script
        self.log = log
        self.events = events
        self.fillers = frozenset(fillers)
        self.function_words = function_words
        self.sentence = self._first_sentence()
        self.position = -1
        self.take: Take | None = None
        self.stream = _Stream()
        self.alignment: Alignment | None = None
        self.speaking = False
        self.last_speech_end = 0.0
        self.speech_start: float | None = None
        self.now = 0.0
        self.paused = False
        self.excluded: list[tuple[float, float]] = []
        self.floor = 0.0
        self._fired: set[tuple[int, int]] = set()
        self.final_guess: tuple[int, str] | None = None

    def _first_sentence(self) -> int:
        for sentence in self.script.sentences:
            if sentence.trackable or sentence.kind == ADLIB:
                return sentence.index
        return 0

    @property
    def current(self) -> Sentence:
        return self.script.sentences[self.sentence]

    def variants(self, sentence: Sentence) -> list[list[list[str]]]:
        return [w.variants for w in sentence.words]

    def on_vad(self, speech: bool, time: float) -> None:
        self.now = max(self.now, time)
        if speech:
            self.speaking = True
            self.speech_start = time
        else:
            self.speaking = False
            self.last_speech_end = time
        self._check_completion()

    def on_tick(self, time: float) -> None:
        self.now = max(self.now, time)
        self._check_completion()

    def on_words(self, tokens: list[HypToken], final: bool, replace_from: float | None = None) -> None:
        if self.paused:
            return
        tokens = [t for t in tokens if not self._is_excluded(t) and t.start >= self.floor - 1e-6]
        if replace_from is not None:
            self.stream.committed = [t for t in self.stream.committed if t.end <= replace_from + 1e-6]
            self.stream.committed.extend(t for t in tokens if t.start >= replace_from - 1e-6)
            self.stream.partial = []
        elif final:
            self.stream.committed.extend(tokens)
            self.stream.partial = []
        else:
            self.stream.partial = list(tokens)
        if tokens:
            self.now = max(self.now, tokens[-1].end)
        self._update(final)

    def exclude(self, start: float, end: float) -> None:
        self.excluded.append((start, end))
        self.stream.committed = [t for t in self.stream.committed if not self._is_excluded(t)]
        self.stream.partial = [t for t in self.stream.partial if not self._is_excluded(t)]
        self._update(False)

    def _is_excluded(self, token: HypToken) -> bool:
        middle = (token.start + token.end) / 2
        return any(a - 0.05 <= middle <= b + 0.05 for a, b in self.excluded)

    def _update(self, final: bool) -> None:
        sentence = self.current
        if sentence.kind == ADLIB:
            self._update_adlib(final)
            return
        if not sentence.trackable:
            return
        tokens = self.stream.tokens
        if not tokens:
            return
        if self.take is None:
            self._maybe_start(tokens, final)
            return
        if self._check_restart(tokens):
            return
        if self.position <= 1 and self._check_jump_back(tokens):
            return
        self.alignment = align(self.variants(sentence), [t.text for t in tokens])
        if not final:
            self.alignment = self._confirmed(self.alignment)
        if self._check_next_sentence(tokens):
            return
        self._set_position(self.alignment.last_word)
        self._check_completion()

    @staticmethod
    def _confirmed(alignment: Alignment) -> Alignment:
        runs: list[list] = []
        for match in alignment.matches:
            if runs and match.word - runs[-1][-1].word <= RUN_GAP:
                runs[-1].append(match)
            else:
                runs.append([match])
        kept = runs[0] if runs else []
        for run in runs[1:]:
            if len(run) < JUMP_RUN:
                break
            kept = kept + run
        if len(kept) == len(alignment.matches):
            return alignment
        last = kept[-1].word if kept else -1
        return Alignment(kept, alignment.inserted, [w for w in alignment.skipped if w < last], alignment.score)

    def _maybe_start(self, tokens: list[HypToken], final: bool) -> None:
        tokens = self._expire(tokens)
        if not tokens:
            return
        sentence = self.current
        probe = align(self.variants(sentence)[:6], [t.text for t in tokens])
        if not self._is_start(probe, len(sentence.words)):
            return
        first = probe.matches[0]
        index = self._reach_back(tokens, first.first_token) if first.word > 0 else first.first_token
        self._emit_off_script(tokens[:index], inside=False)
        start = tokens[index].start
        if first.word > 0 and index == first.first_token:
            start = self._speech_onset(start)
        self._keep_from(start)
        self._start_take(start)
        self._update(final)

    def _expire(self, tokens: list[HypToken]) -> list[HypToken]:
        """Lets go of what can no longer begin the sentence: speech before a long pause or older than the window."""
        newest = tokens[-1].end
        cut = 0
        for i, token in enumerate(tokens):
            if token.start < newest - START_WINDOW or (i > 0 and token.start - tokens[i - 1].end > START_GAP):
                cut = i if token.start >= newest - START_WINDOW else i + 1
        if cut == 0:
            return tokens
        self._emit_off_script(tokens[:cut], inside=False)
        if cut < len(tokens):
            self._keep_from(tokens[cut].start)
        else:
            self._consume(tokens[-1].end)
        return tokens[cut:]

    def _speech_onset(self, start: float) -> float:
        """When the recognizer dropped the first word altogether, the take still begins where speech did."""
        onset = self.speech_start
        if onset is not None and 0 < start - onset <= OPENER_GAP:
            return onset
        return start

    def _reach_back(self, tokens: list[HypToken], index: int) -> int:
        if index == 0 or tokens[index].start - tokens[index - 1].end > OPENER_GAP:
            return index
        opener = self.current.words[0].variants
        span = max(len(v) for v in opener)
        scored = [(word_similarity(opener, [t.text for t in tokens[index - size:index]]), -size) for size in range(1, min(span, index) + 1)]
        best, size = max(scored)
        return index + size if best >= OPENER_SIMILARITY else index

    @staticmethod
    def _is_start(probe: Alignment, length: int) -> bool:
        matches = probe.matches
        if not matches:
            return False
        if len(matches) >= 3:
            return True
        if len(matches) >= 2 and matches[0].word <= 1:
            return True
        return length <= 2 and matches[0].word == 0

    def _consume(self, until: float) -> None:
        self.floor = max(self.floor, until)
        self.stream.clear()

    def _keep_from(self, start: float) -> None:
        self.floor = max(self.floor, start)
        self.stream.keep_from(start)

    def _start_take(self, start: float) -> None:
        sentence = self.current
        begin = max(0.0, start - PREROLL)
        self.take = self.log.new_take(sentence.index, begin, sentence.text)
        self.position = -1
        self.alignment = None
        self.events.take_started(self.take)
        for token in sentence.leading_cues():
            self._fire(token, -1, begin)

    def _check_restart(self, tokens: list[HypToken]) -> bool:
        """The opening said again after the reading got past it. It can start at the second word (the
        first one misheard), and it's looked for anywhere in the take: the aligner may have folded the
        repeat into the sentence ("configurations, thirty-two different configurations")."""
        if self.alignment is None or self.position < 2:
            return False
        words = self.current.words
        head = self.variants(self.current)[:min(4, len(words))]
        texts = [t.text for t in tokens]
        for i in range(1, len(tokens) - 1):
            probe = align(head, texts[i:i + 6])
            if len(probe.matches) < 2:
                continue
            first, second = probe.matches[0], probe.matches[1]
            if first.first_token != 0 or first.word > 1 or second.word != first.word + 1 or self._recurs(first.word):
                continue
            if align(self.variants(self.current), texts[:i]).last_word < second.word:
                continue
            restart_at = tokens[self._reach_back(tokens, i) if first.word > 0 else i].start
            if restart_at <= self.take.start + PREROLL + 1e-6:
                continue
            self.reject("restart", end=restart_at)
            self._keep_from(restart_at)
            self._start_take(restart_at)
            self._update(False)
            return True
        return False

    def _recurs(self, word: int) -> bool:
        """Whether the script itself says these two words again later in the sentence."""
        keys = [w.key for w in self.current.words]
        pair = keys[word:word + 2]
        return any(keys[k:k + 2] == pair for k in range(word + 2, len(keys) - 1))

    def _check_jump_back(self, tokens: list[HypToken]) -> bool:
        previous = self.script.previous_sentence(self.sentence)
        if previous is None or len(tokens) < 3:
            return False
        prev_sentence = self.script.sentences[previous]
        if not prev_sentence.trackable:
            return False
        texts = [t.text for t in tokens]
        here = align(self.variants(self.current)[:4], texts)
        there = align(self.variants(prev_sentence)[:4], texts)
        if len(there.matches) >= 3 and len(there.matches) > len(here.matches) + 1 and there.matches[0].word == 0:
            start = tokens[there.matches[0].first_token].start
            if self.take:
                self.reject("jump-back", end=start)
            self._keep_from(start)
            self._go_to(previous)
            self._start_take(start)
            self._update(False)
            return True
        return False

    def _check_next_sentence(self, tokens: list[HypToken]) -> bool:
        alignment = self.alignment
        words = self.current.words
        if alignment is None or alignment.last_word < len(words) - 2:
            return False
        following = self.script.next_sentence(self.sentence)
        if following is None:
            return False
        next_sentence = self.script.sentences[following]
        if next_sentence.kind == ADLIB:
            return False
        last_token = max((m.last_token for m in alignment.matches), default=-1)
        tail = tokens[last_token + 1:]
        if len(tail) < 2:
            return False
        probe = align(self.variants(next_sentence)[:4], [t.text for t in tail])
        if len(probe.matches) >= 2 and probe.matches[0].word == 0:
            start = tail[probe.matches[0].first_token].start
            self._set_position(len(words) - 1)
            self.complete(end=tokens[last_token].end + TAIL)
            self._keep_from(start)
            self._start_take(start)
            self._update(False)
            return True
        return False

    def _check_completion(self) -> None:
        if self.take is None or self.alignment is None or self.paused or self.speaking:
            return
        words = self.current.words
        if not self.alignment.matches:
            return
        tokens = self.stream.tokens
        last = self.alignment.matches[-1]
        if last.last_token >= len(tokens):
            return
        end = tokens[last.last_token].end
        pause = COMPLETION_PAUSE
        self.final_guess = None
        if self.alignment.last_word < len(words) - 1:
            trailing = tokens[last.last_token + 1:]
            if not (len(words) >= 4 and self.alignment.last_word >= len(words) - 2 and trailing):
                return
            self.final_guess = (len(words) - 1, " ".join(t.text for t in trailing))
            end = trailing[-1].end
            pause = 0.7
        if self.now - max(end, self.last_speech_end) >= pause or self.now - end >= pause + 0.8:
            self.complete(end=end + TAIL)

    def _set_position(self, word: int) -> None:
        if word == self.position:
            return
        previous = self.position
        self.position = word
        self.events.position_changed(self.sentence, word)
        if word > previous:
            for position in range(previous + 1, word + 1):
                for token in self.current.cues_after(position):
                    self._fire(token, position, self.now)

    def _fire(self, token: Token, position: int, time: float) -> None:
        key = (self.sentence, id(token))
        if key in self._fired:
            return
        self._fired.add(key)
        self.events.cue_reached(token, time)

    def _timings(self) -> list[WordTiming]:
        if self.alignment is None:
            return []
        tokens = self.stream.tokens
        words = self.current.words
        result = []
        for match in self.alignment.matches:
            if match.last_token >= len(tokens):
                continue
            first, last = tokens[match.first_token], tokens[match.last_token]
            result.append(WordTiming(words[match.word].index, words[match.word].display, first.start, last.end))
        return result

    def _deviations(self) -> list[dict]:
        if self.alignment is None:
            return []
        tokens = self.stream.tokens
        words = self.current.words
        guess = self.final_guess
        extra = []
        if guess is not None and words[guess[0]].key not in self.function_words:
            extra.append({"word": words[guess[0]].index, "text": words[guess[0]].display, "kind": "substituted", "heard": guess[1]})
        deviations = [
            {"word": words[i].index, "text": words[i].display, "kind": "skipped"}
            for i in self.alignment.skipped
            if words[i].key not in self.function_words
        ]
        for match in self.alignment.matches:
            if match.similarity < SUBSTITUTION_SIMILARITY and words[match.word].key not in self.function_words:
                heard = " ".join(t.text for t in tokens[match.first_token:match.last_token + 1])
                deviations.append({"word": words[match.word].index, "text": words[match.word].display, "kind": "substituted", "heard": heard})
        return deviations + extra

    def _inside_off_script(self) -> None:
        if self.alignment is None or not self.alignment.matches:
            return
        tokens = self.stream.tokens
        first = self.alignment.matches[0].first_token
        last = self.alignment.matches[-1].last_token
        run: list[int] = []
        for index in self.alignment.inserted:
            if not first < index < last or index >= len(tokens):
                continue
            if run and run[-1] != index - 1:
                self._emit_off_script([tokens[i] for i in run], inside=True)
                run = []
            run.append(index)
        if run:
            self._emit_off_script([tokens[i] for i in run], inside=True)

    def _emit_off_script(self, tokens: list[HypToken], inside: bool) -> None:
        if not tokens:
            return
        text = " ".join(t.text for t in tokens)
        filler = all(t.text in self.fillers for t in tokens) or text in self.fillers
        if not filler and tokens[-1].end - tokens[0].start < 0.25 and len(tokens) < 2:
            return
        self.events.off_script(tokens[0].start, tokens[-1].end, text, inside, filler)

    def complete(self, end: float | None = None) -> Take | None:
        take = self.take
        if take is None:
            return None
        take.end = end if end is not None else self.now
        take.words = self._timings()
        take.deviations = self._deviations()
        take.status = COMPLETE
        self._inside_off_script()
        self.take = None
        self.alignment = None
        # Whatever was said after the last word may already be the next sentence's opening.
        self._keep_from(take.words[-1].end if take.words else take.end)
        self.log.save()
        self.events.take_completed(take)
        following = self.script.next_sentence(self.sentence)
        if following is not None:
            self._go_to(following)
        return take

    def reject(self, reason: str, end: float | None = None) -> Take | None:
        take = self.take
        if take is None:
            return None
        take.end = end if end is not None else self.now
        take.words = self._timings()
        take.status = REJECTED
        take.reason = reason
        self.take = None
        self.alignment = None
        self.log.save()
        self.events.take_rejected(take)
        return take

    def retake(self, reason: str = "command", end: float | None = None) -> None:
        self.reject(reason, end)
        self._consume(end if end is not None else self.now)
        self.position = -1
        self.events.position_changed(self.sentence, -1)

    def go_next(self) -> None:
        adlib = self.current.kind == ADLIB
        if self.take and (adlib or self.alignment and self.alignment.matches):
            self.complete()
            return
        if self.take:
            self.reject("skipped")
        self._consume(self.now)
        following = self.script.next_sentence(self.sentence)
        if following is not None:
            self._go_to(following)

    def go_back(self) -> None:
        if self.take:
            self.reject("back")
        self._consume(self.now)
        previous = self.script.previous_sentence(self.sentence)
        if previous is not None:
            self._go_to(previous)

    def go_to(self, sentence: int) -> None:
        if self.take:
            self.reject("jump")
        self._consume(self.now)
        self._go_to(sentence)

    def _go_to(self, sentence: int) -> None:
        self.sentence = sentence
        self.position = -1
        self.events.sentence_changed(sentence)
        self.events.position_changed(sentence, -1)
        if self.current.kind == ADLIB:
            self.events.position_changed(sentence, -1)

    def _update_adlib(self, final: bool) -> None:
        tokens = self.stream.tokens
        if not tokens:
            return
        if self.take is None:
            self.take = self.log.new_take(self.sentence, max(0.0, tokens[0].start - PREROLL), self.current.note)
            self.events.take_started(self.take)
        following = self.script.next_sentence(self.sentence)
        if following is None:
            return
        next_sentence = self.script.sentences[following]
        if not next_sentence.trackable:
            return
        probe = align(self.variants(next_sentence)[:4], [t.text for t in tokens])
        if len(probe.matches) >= 2 and probe.matches[0].word == 0:
            start = tokens[probe.matches[0].first_token].start
            take = self.take
            take.end = start - 0.05
            take.status = COMPLETE
            self.take = None
            self.log.save()
            self.events.take_completed(take)
            self._keep_from(start)
            self._go_to(following)
            self._start_take(start)
            self._update(final)
        elif final:
            self._consume(tokens[-1].end)
