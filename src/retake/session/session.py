from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Protocol

from ..languages.packs import LanguagePack
from ..script.lexicon import Lexicon
from ..script.normalize import hypothesis_tokens
from ..script.model import ADLIB, Script
from . import takes as kinds
from .aligner import HypToken
from .coach import REQUIRE, WARN, CoachSettings, PracticeHistory, flag_entry
from .drill import COMMAND_WINDOW, LONG_ATTEMPT, ON_DEMAND_TIMES, PASSED, SKIPPED, UNCOACHED, Drill, DrillWord
from .takes import COMPLETE, REJECTED, Take, TakeLog
from .tracker import ScriptTracker

READY = "ready"
LISTENING = "listening"
PAUSED = "paused"
REVIEW = "review"
STOPPED = "stopped"

RECENT = 6.0


@dataclass
class SessionSettings:
    rehearsal: bool = False
    coach: CoachSettings = field(default_factory=CoachSettings)
    extra_speech: str = "between"
    deviations: str = WARN


class SessionListener(Protocol):
    def state_changed(self, state: str) -> None: ...
    def position_changed(self, sentence: int, word: int) -> None: ...
    def sentence_changed(self, sentence: int) -> None: ...
    def takes_changed(self) -> None: ...
    def coach_feedback(self, take: Take, flagged: list[dict], deviations: list[dict]) -> None: ...
    def notice(self, kind: str, text: str) -> None: ...
    def request(self, message: dict) -> None: ...
    def review_changed(self, queue: list[int], index: int) -> None: ...
    def drill_changed(self, drill: dict) -> None: ...
    def marks_changed(self, red: list[int], warned: list[int]) -> None: ...
    def stop_requested(self) -> None: ...


class Session:
    def __init__(
        self,
        log: TakeLog,
        settings: SessionSettings,
        listener: SessionListener,
        script: Script,
        pack: LanguagePack | None = None,
        native: LanguagePack | None = None,
        history: PracticeHistory | None = None,
        start_sentence: int | None = None,
        lexicon: Lexicon | None = None,
        pickup: list[int] | None = None,
    ):
        self.log = log
        self.settings = settings
        self.listener = listener
        self.script = script
        self.pack = pack
        self.native = native
        self.history = history or PracticeHistory(None)
        self.lexicon = lexicon or Lexicon(None)
        self.pickup = list(pickup or [])
        self.state = READY
        self.now = 0.0
        self._requests = itertools.count(1)
        self._pending_scores: dict[int, int] = {}
        self._pause_marker: kinds.Marker | None = None
        self._last_section: int | None = None
        self._chapters = 0
        self.last_feedback: tuple[Take, list[dict]] | None = None
        self.review_queue: list[int] = []
        self.review_index = 0
        self.pending_commands: list[dict] = []
        self.words_horizon = 0.0
        self.tracking_active = True
        self.drill: Drill | None = None
        self._drill_requests: set[int] = set()
        self._drill_marker: kinds.Marker | None = None
        self.red: dict[int, list[int]] = {}
        self.warned: dict[int, list[int]] = {}
        # Words skipped in a drill are left alone for the rest of this recording.
        self.skipped: set[str] = set()
        fillers = pack.fillers if pack else ()
        function_words = pack.function_words if pack else frozenset()
        self.tracker = ScriptTracker(script, log, self, fillers, function_words)
        if start_sentence is not None and 0 <= start_sentence < len(script.sentences):
            self.tracker.sentence = start_sentence

    def start(self) -> None:
        if self.pickup:
            self.review_queue = list(self.pickup)
            self.review_index = 0
            self._set_state(REVIEW)
            self.listener.review_changed(self.review_queue, 0)
            self.tracker.go_to(self.review_queue[0])
            self.sentence_changed(self.tracker.sentence)
            self.position_changed(self.tracker.sentence, -1)
            return
        self._set_state(LISTENING)
        self.sentence_changed(self.tracker.sentence)
        self.position_changed(self.tracker.sentence, -1)

    def stop(self) -> None:
        if self.state == STOPPED:
            return
        if self.drill is not None:
            self._end_drill()
        if self._pause_marker is not None:
            self._close_pause()
        tracker = self.tracker
        if tracker.take is not None:
            if tracker.alignment and tracker.alignment.last_word >= len(tracker.current.words) - 1:
                tracker.complete()
            else:
                tracker.reject("stopped")
        self._set_state(STOPPED)
        self.log.save()

    def _set_state(self, state: str) -> None:
        self.state = state
        self.listener.state_changed(state)

    def tick(self, time: float) -> None:
        self.now = max(self.now, time)
        self.tracker.on_tick(time)
        drill = self.drill
        if drill is not None and drill.listen_from is None and time > drill.voice_deadline:
            drill.voice_ended(time)
            self.listener.drill_changed(drill.as_dict())
        if drill is not None and drill.held is not None and time >= drill.held[1]:
            score, _ = drill.held
            drill.held = None
            self._apply_drill_score(score)
        self._run_commands()

    def on_engine(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "vad":
            self.now = max(self.now, event["time"])
            self.tracker.on_vad(event["speech"], event["time"])
            if self.drill is not None:
                attempt = self.drill.on_vad(event["speech"], event["time"])
                if attempt is not None:
                    self._score_attempt(*attempt)
            self._run_commands()
        elif kind == "words":
            if event["words"]:
                self.words_horizon = max(self.words_horizon, event["words"][-1]["end"])
            if self.state in (LISTENING, REVIEW, PAUSED):
                tokens = self._tokens(event["words"])
                self.tracker.on_words(tokens, event.get("final", False), event.get("replace_from"))
            self._run_commands()
        elif kind == "progress":
            self.words_horizon = max(self.words_horizon, event["time"])
            self._run_commands()
        elif kind == "command":
            self._on_command(event)
        elif kind == "score":
            self._on_score(event)

    def _tokens(self, words: list[dict]) -> list[HypToken]:
        numbers = self.pack.numbers if self.pack else None
        tokens = []
        for word in words:
            parts = hypothesis_tokens(word["text"], numbers)
            if not parts:
                continue
            span = (word["end"] - word["start"]) / len(parts)
            for index, part in enumerate(parts):
                start = word["start"] + index * span
                tokens.append(HypToken(part, start, start + span))
        return tokens

    def _on_command(self, event: dict) -> None:
        start, end = event["start"], event["end"]
        self.log.add_marker(kinds.COMMAND, start, end, event["action"], phrase=event.get("phrase", ""))
        self.tracker.exclude(start, end)
        self.pending_commands.append(event)
        self.listener.notice("command", event["action"])
        self._run_commands()

    def _run_commands(self) -> None:
        while self.pending_commands:
            event = self.pending_commands[0]
            caught_up = self.words_horizon >= event["end"] + 0.3 or not self.tracking_active
            if not caught_up:
                return
            self.pending_commands.pop(0)
            self.handle(event["action"], event.get("arg"), time=event["start"], source="voice")

    def handle(self, action: str, arg=None, time: float | None = None, source: str = "key") -> None:
        time = self.now if time is None else time
        if action == "toggle_pause":
            action = "resume" if self.state == PAUSED else "pause"
        if self.drill is not None:
            if action == "skip":
                self._next_drill_word(SKIPPED)
                return
            if action in ("pause", "again", "next", "back", "goto", "stop"):
                self._end_drill()
        elif action == "drill":
            self._drill_on_demand()
            return
        if action == "uncoach":
            self._uncoach(str(arg) if arg else None)
            return
        if action == "pause" and self.state in (LISTENING, REVIEW):
            self.tracker.paused = True
            self._pause_marker = self.log.add_marker(kinds.PAUSE, time, time, "pause")
            self._resume_state = self.state
            self._set_state(PAUSED)
        elif action == "resume" and self.state == PAUSED:
            self._close_pause()
        elif action == "again":
            self._again(time, source)
        elif action == "next":
            self.tracker.go_next()
        elif action == "back":
            self.tracker.go_back()
        elif action == "goto" and arg is not None:
            self.tracker.go_to(int(arg))
        elif action == "mark":
            self._chapters += 1
            self.log.add_marker(kinds.MARK, time, time, arg or f"Mark {self._chapters}")
            self.listener.notice("mark", arg or f"Mark {self._chapters}")
        elif action == "listen":
            self._listen()
        elif action == "say" and arg:
            self.listener.request({"type": "tts", "text": str(arg), "slow": True})
        elif action == "stop":
            # The whole recording stops (recorder, video, the studio), the same as pressing Enter.
            self.listener.stop_requested()
            return
        self.listener.takes_changed()

    def _close_pause(self) -> None:
        marker = self._pause_marker
        if marker is not None:
            marker.end = self.now
            self.log.save()
        self._pause_marker = None
        self.tracker.paused = False
        self._set_state(getattr(self, "_resume_state", LISTENING))

    def _again(self, time: float, source: str) -> None:
        reason = "command" if source == "voice" else source
        tracker = self.tracker
        if tracker.take is not None:
            tracker.retake(reason, end=time)
            return
        recent = self._recent_take(time)
        if recent is not None:
            recent.status = REJECTED
            recent.reason = reason
            self.log.save()
            self.take_rejected(recent)
            tracker.go_to(recent.sentence)
            return
        tracker.retake(reason, end=time)

    def _recent_take(self, time: float) -> Take | None:
        if self.last_feedback is not None:
            take = self.last_feedback[0]
            if take.status == COMPLETE:
                return take
        complete = [t for t in self.log.takes if t.status == COMPLETE and t.end is not None]
        if complete and time - complete[-1].end <= RECENT:
            return complete[-1]
        return None

    def _listen(self) -> None:
        if self.drill is not None:
            self._say_drill_word()
            return
        if self.last_feedback and self.last_feedback[1]:
            entry = self.last_feedback[1][0]
            self.listener.request({"type": "tts", "text": entry["text"], "slow": True, "ipa": entry.get("expected") or None})
            return
        sentence = self.tracker.current
        if sentence.words:
            index = min(max(self.tracker.position + 1, 0), len(sentence.words) - 1)
            word = sentence.words[index]
            self.listener.request({"type": "tts", "text": word.display.strip(".,;:!?"), "slow": True,
                                   "ipa": word.override_ipa or self.lexicon.word_ipa(word.key)})

    def tts_played(self, start: float, end: float, text: str) -> None:
        self.log.add_marker(kinds.TTS, start, end, text)
        self.tracker.exclude(start, end)
        drill = self.drill
        if drill is not None and drill.listen_from is None:
            drill.voice_ended(end)
            self.listener.drill_changed(drill.as_dict())

    def position_changed(self, sentence: int, word: int) -> None:
        self.listener.position_changed(sentence, word)

    def sentence_changed(self, sentence: int) -> None:
        self.last_feedback = None if self.state != REVIEW else self.last_feedback
        current = self.script.sentences[sentence]
        self.listener.request({
            "type": "context",
            "text": current.text if current.kind != ADLIB else "",
            "words": [w.display.strip(".,;:!?\"'()") for w in current.words],
        })
        self.listener.sentence_changed(sentence)

    def take_started(self, take: Take) -> None:
        if take.sentence is not None:
            section = self.script.sentences[take.sentence].section
            if section >= 0 and section != self._last_section:
                self._last_section = section
                title = self.script.sections[section].title
                if not any(m.kind == kinds.CHAPTER and m.label == title for m in self.log.markers):
                    self.log.add_marker(kinds.CHAPTER, take.start, take.start, title)
        self.listener.takes_changed()

    def take_completed(self, take: Take) -> None:
        self.listener.takes_changed()
        is_adlib = take.sentence is not None and self.script.sentences[take.sentence].kind == ADLIB
        if is_adlib:
            self.log.add_marker(kinds.ADLIB, take.start, take.end, "ad-lib")
        else:
            if self.settings.coach.enabled and take.words:
                self._request_score(take)
            if take.deviations:
                self._apply_deviations(take)
        if self.state == REVIEW:
            if take.sentence == self.review_queue[self.review_index]:
                self._advance_review()
        elif self.script.next_sentence(take.sentence) is None:
            self._end_of_script()

    def take_rejected(self, take: Take) -> None:
        self.listener.takes_changed()

    def off_script(self, start: float, end: float, text: str, inside: bool, filler: bool) -> None:
        kind = kinds.FILLER if filler else kinds.OFF_SCRIPT
        self.log.add_marker(kind, start, end, text, inside=inside)
        if not filler:
            self.listener.notice("off-script", text)

    def _request_score(self, take: Take) -> None:
        request = next(self._requests)
        self._pending_scores[request] = take.id
        words = []
        for timing in take.words:
            override = None
            text = timing.text
            if timing.word >= 0:
                word = self.script.words[timing.word]
                override = word.override_ipa or self.lexicon.word_ipa(word.key)
                text = word.spoken or word.display
            words.append({
                "index": timing.word,
                "text": text.strip(".,;:!?\"'()[]"),
                "override": override,
                "start": timing.start,
                "end": timing.end,
            })
        self.listener.request({
            "type": "score",
            "request": request,
            "take": take.id,
            "start": take.start,
            "end": take.end,
            "words": words,
        })

    def uncoached(self, key: str) -> bool:
        return key in self.history.uncoached() or self.lexicon.uncoached(key)

    def _word_key(self, index: int, text: str) -> str:
        if 0 <= index < len(self.script.words):
            return self.script.words[index].key
        return text.lower().strip(".,;:!?\"'()[]")

    def _on_score(self, event: dict) -> None:
        request = event.get("request")
        if request in self._drill_requests:
            self._drill_requests.discard(request)
            self._drill_scored(event)
            return
        take_id = self._pending_scores.pop(request, None)
        take = self.log.take(take_id) if take_id is not None else None
        if take is None or event.get("error"):
            return
        coach = self.settings.coach
        results = event.get("words", [])
        flagged = []
        for timing, result in zip(take.words, results):
            timing.score = result.get("score")
            timing.heard = result.get("heard", "")
            key = self._word_key(timing.word, timing.text)
            if self.uncoached(key):
                continue
            entry = flag_entry({**result, "text": timing.text, "word": timing.word}, coach.threshold, self.native)
            self.history.record(key, entry is not None)
            if entry is not None:
                flagged.append(entry)
                if self.history.should_flag(key, coach.auto_flag_misses):
                    self.history.flag(key)
                    self.listener.notice("auto-flag", key)
        scores = [r["score"] for r in results if r.get("score") is not None]
        take.score = sum(scores) / len(scores) if scores else None
        take.flagged = flagged
        self.history.save()
        self.log.save()
        failing = [e for e in flagged if coach.require and e["score"] < coach.require and self._word_key(e["word"], e["text"]) not in self.skipped]
        self._set_marks(take.sentence, [e["word"] for e in failing], [e["word"] for e in flagged if e not in failing])
        if not flagged:
            self.listener.takes_changed()
            return
        if coach.timing == "review":
            if take.sentence is not None and take.sentence not in self.review_queue:
                self.review_queue.append(take.sentence)
            self.listener.takes_changed()
            return
        self.last_feedback = (take, flagged)
        self.listener.coach_feedback(take, flagged, [])
        if failing and take.status == COMPLETE:
            if coach.drill_times > 0 and self.drill is None:
                self._start_drill(take, failing)
            else:
                self._send_back(take, "coach")
        self.listener.takes_changed()

    def _set_marks(self, sentence: int | None, red: list[int], warned: list[int]) -> None:
        """The sentence's last take colors the prompter: red for words that sank it, yellow for words
        that were only warned about. A later take of the sentence replaces both."""
        if sentence is None or (self.red.get(sentence, []), self.warned.get(sentence, [])) == (red, warned):
            return
        for marks, words in ((self.red, red), (self.warned, warned)):
            if words:
                marks[sentence] = words
            else:
                marks.pop(sentence, None)
        self.listener.marks_changed(sorted(w for ws in self.red.values() for w in ws), sorted(w for ws in self.warned.values() for w in ws))

    def _drill_on_demand(self) -> None:
        """Drills the words of the current sentence that were warned about, or of the previous one
        when the current has none; the sentence is then read again."""
        current = self.tracker.sentence
        previous = self.script.previous_sentence(current)
        for sentence in (current, previous):
            if sentence is None:
                continue
            marked = set(self.red.get(sentence, [])) | set(self.warned.get(sentence, []))
            take = next((t for t in reversed(self.log.takes) if t.sentence == sentence and t.flagged), None)
            entries = [e for e in take.flagged if e.get("word") in marked and self._word_key(e.get("word", -1), e.get("text", "")) not in self.skipped] if take and marked else []
            if entries:
                self._start_drill(take, entries, reason="drill", interrupt=True)
                return
        self.listener.notice("drill-none", "")

    def _start_drill(self, take: Take, failing: list[dict], reason: str = "coach", interrupt: bool = False) -> None:
        take.status = REJECTED
        take.reason = reason
        self.log.save()
        # The cue plays at once; the reference voice needs a moment to be synthesized.
        self.listener.notice("retake", "drill")
        tracker = self.tracker
        if tracker.take is not None and (interrupt or tracker.take.start >= (take.end or 0)):
            tracker.reject(reason)
        tracker.go_to(take.sentence)
        tracker.paused = True
        words = []
        for entry in sorted(failing, key=lambda e: e.get("word", -1)):
            index = entry.get("word", -1)
            script_word = self.script.words[index] if 0 <= index < len(self.script.words) else None
            text = (script_word.spoken or script_word.display) if script_word else entry.get("text", "")
            override = (script_word.override_ipa or self.lexicon.word_ipa(script_word.key)) if script_word else None
            words.append(DrillWord(index, text.strip(".,;:!?\"'()[]"), self._word_key(index, text), override, entry))
        self.drill = Drill(take, words, int(self.settings.coach.drill_times) or ON_DEMAND_TIMES)
        self._drill_marker = self.log.add_marker(kinds.DRILL, self.now, self.now, "drill")
        self._say_drill_word()

    def _say_drill_word(self) -> None:
        drill = self.drill
        drill.saying(self.now)
        self.listener.drill_changed(drill.as_dict())
        word = drill.word
        self.listener.request({"type": "tts", "text": word.text, "ipa": word.override or word.entry.get("expected") or None, "slow": True})

    def _score_attempt(self, start: float, end: float) -> None:
        drill = self.drill
        request = next(self._requests)
        self._drill_requests.add(request)
        drill.scoring = True
        drill.attempt = (start, end)
        word = drill.word
        self.listener.request({
            "type": "score",
            "request": request,
            "take": None,
            "start": max(0.0, start - 0.1),
            "end": end + 0.15,
            "words": [{"index": word.index, "text": word.text, "override": word.override, "start": start, "end": end}],
        })

    def _drill_scored(self, event: dict) -> None:
        drill = self.drill
        if drill is None or drill.done:
            return
        if event.get("error"):
            drill.scoring = False
            return
        score = (event.get("words") or [{}])[0].get("score")
        start, end = drill.attempt or (0.0, 0.0)
        if end - start >= LONG_ATTEMPT:
            drill.held = (score, end + COMMAND_WINDOW)
            return
        self._apply_drill_score(score)

    def _apply_drill_score(self, score: float | None) -> None:
        drill = self.drill
        if drill is None or drill.done:
            return
        start, end = drill.attempt or (0.0, 0.0)
        if any(m.start < end and m.end > start for m in self.log.markers_of(kinds.COMMAND)):
            # It was a voice command ("retake, say it"), not a try at the word.
            drill.scoring = False
            return
        passed = drill.scored(score, self.settings.coach.threshold)
        self.history.record(drill.word.key, not passed)
        self.listener.notice("drill-pass" if passed else "drill-miss", drill.word.text)
        if drill.passes >= drill.times:
            self._next_drill_word(PASSED)
        else:
            self._say_drill_word()

    def _next_drill_word(self, outcome: str) -> None:
        drill = self.drill
        index = drill.word.index
        if outcome == SKIPPED:
            self.skipped.add(drill.word.key)
        drill.finish_word(outcome)
        self.log.save()
        if outcome == UNCOACHED:
            sentence = drill.take.sentence
            self._set_marks(sentence, [w for w in self.red.get(sentence, []) if w != index], self.warned.get(sentence, []))
        if drill.done:
            self._end_drill()
            self.tracker.go_to(drill.take.sentence)
        else:
            self._say_drill_word()

    def _end_drill(self) -> None:
        self.drill = None
        if self._drill_marker is not None:
            self._drill_marker.end = self.now
            self._drill_marker = None
        self._drill_requests.clear()
        self.history.save()
        self.log.save()
        self.tracker.paused = self.state == PAUSED
        self.listener.drill_changed({})

    def _uncoach(self, key: str | None) -> None:
        """Never scores, drills or guides this word again (names, mostly); during a drill, moves on."""
        drill = self.drill
        if key is None and drill is not None:
            key = drill.word.key
        if not key:
            return
        self.history.set_coached(key, False)
        self.history.save()
        self.listener.notice("uncoached", key)
        if drill is not None and drill.word.key == key:
            self._next_drill_word(UNCOACHED)

    def _apply_deviations(self, take: Take) -> None:
        policy = self.settings.deviations
        if policy == "accept":
            return
        self.listener.coach_feedback(take, [], take.deviations)
        if policy == REQUIRE:
            self._send_back(take, "deviation")

    def _send_back(self, take: Take, reason: str) -> None:
        take.status = REJECTED
        take.reason = reason
        self.log.save()
        tracker = self.tracker
        if tracker.take is not None and tracker.take.start >= (take.end or 0):
            tracker.reject(reason)
        tracker.go_to(take.sentence)
        self.listener.notice("retake", reason)

    def _end_of_script(self) -> None:
        if self.review_queue:
            self.review_index = 0
            self._set_state(REVIEW)
            self.listener.review_changed(self.review_queue, 0)
            self.tracker.go_to(self.review_queue[0])
        else:
            self.listener.notice("end", "")

    def _advance_review(self) -> None:
        self.review_index += 1
        if self.review_index >= len(self.review_queue):
            self.review_queue = []
            self.listener.review_changed([], 0)
            if self.pickup:
                self.listener.notice("pickups-done", "")
                return
            self._set_state(LISTENING)
            self.listener.notice("end", "")
            return
        self.listener.review_changed(self.review_queue, self.review_index)
        self.tracker.go_to(self.review_queue[self.review_index])
