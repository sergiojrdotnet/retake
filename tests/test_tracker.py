from retake.languages import packs
from retake.script.parser import parse
from retake.session.aligner import HypToken, align
from retake.session.takes import COMPLETE, REJECTED, TakeLog
from retake.session.tracker import ScriptTracker

SCRIPT = """
# Demo

We flush the cache to disk. Then we measure P99 latency at 10k events.

[On the terminal] Finally we compare 2026 results.

(AD-LIB)
talk freely
(/AD-LIB)

That is all for today.
"""


class Recorder:
    def __init__(self):
        self.events = []

    def __getattr__(self, name):
        def handler(*args):
            self.events.append((name, args))
        return handler

    def of(self, name):
        return [args for event, args in self.events if event == name]


def tokens(text, start, step=0.3):
    result = []
    t = start
    for word in text.split():
        result.append(HypToken(word, t, t + step * 0.8))
        t += step
    return result, t


def make():
    script = parse(SCRIPT, packs.get("en"))
    log = TakeLog()
    events = Recorder()
    tracker = ScriptTracker(script, log, events, fillers=packs.get("en").fillers)
    return script, log, events, tracker


def speak(tracker, text, start, gap=0.6):
    words, end = tokens(text, start)
    tracker.on_vad(True, start)
    tracker.on_words(words, final=True)
    tracker.on_vad(False, end)
    tracker.on_tick(end + gap)
    return end + gap


def test_alignment_handles_numbers_and_spans():
    script = parse("Measure P99 at 10k and real-time 2026.", packs.get("en"))
    variants = [w.variants for w in script.words]
    spoken = "measure p ninety nine at ten k and real time twenty twenty six".split()
    result = align(variants, spoken)
    assert [m.word for m in result.matches] == list(range(len(variants)))


def test_reads_sentences_in_order():
    script, log, events, tracker = make()
    t = speak(tracker, "we flush the cache to disk", 0.0)
    t = speak(tracker, "then we measure p ninety nine latency at ten k events", t)
    complete = [take for take in log.takes if take.status == COMPLETE]
    assert [take.sentence for take in complete] == [0, 1]
    assert tracker.sentence == 2


def test_restart_rejects_partial_take():
    script, log, events, tracker = make()
    words, t = tokens("we flush the uh we flush the cache to disk", 0.0)
    tracker.on_vad(True, 0.0)
    for i in range(1, len(words) + 1):
        tracker.on_words(words[:i], final=False)
    tracker.on_words(words, final=True)
    tracker.on_vad(False, t)
    tracker.on_tick(t + 0.6)
    assert [take.status for take in log.takes] == [REJECTED, COMPLETE]
    assert log.takes[0].reason == "restart"


def test_retake_command_redoes_the_sentence():
    script, log, events, tracker = make()
    t = speak(tracker, "we flush the cache to disk", 0.0)
    t = speak(tracker, "then we measure p ninety nine latency at ten k events", t)
    t = speak(tracker, "finally we compare", t)
    tracker.retake()
    t = speak(tracker, "finally we compare twenty twenty six results", t)
    statuses = [(take.sentence, take.status) for take in log.takes]
    assert statuses[-2:] == [(2, REJECTED), (2, COMPLETE)]


def test_adlib_then_next_sentence():
    script, log, events, tracker = make()
    t = speak(tracker, "we flush the cache to disk", 0.0)
    t = speak(tracker, "then we measure p ninety nine latency at ten k events", t)
    t = speak(tracker, "finally we compare twenty twenty six results", t)
    assert script.sentences[tracker.sentence].kind == "adlib"
    t = speak(tracker, "so this dashboard shows everything that is all for today", t)
    kinds = [script.sentences[take.sentence].kind for take in log.takes if take.status == COMPLETE]
    assert kinds[-2:] == ["adlib", "spoken"]


def test_off_script_between_sentences():
    script, log, events, tracker = make()
    t = speak(tracker, "hold on let me check the light", 0.0)
    t = speak(tracker, "we flush the cache to disk", t)
    off = events.of("off_script")
    assert off and off[0][2].startswith("hold on")
    assert log.takes[0].status == COMPLETE


def test_substitution_is_a_deviation():
    script, log, events, tracker = make()
    speak(tracker, "we flush the cash to desk", 0.0)
    take = log.takes[0]
    kinds = {d["text"]: d["kind"] for d in take.deviations}
    assert kinds.get("disk.") == "substituted"


CANARY = """
# Canary

Thirty-two different configurations, three hundred million events per engine.

Seven days of production traces: about 1.15 million appends.

Stream reads take 56 and 254.
"""


def make_canary():
    script = parse(CANARY, packs.get("en"))
    log = TakeLog()
    events = Recorder()
    tracker = ScriptTracker(script, log, events, fillers=packs.get("en").fillers)
    return script, log, events, tracker


def whisper(tracker, text, start, step=0.3, pause=1.0):
    """Feeds speech the way live Whisper does: the open utterance re-decoded every 0.6 s, final at the pause."""
    words, end = tokens(text, start, step)
    tracker.on_vad(True, start)
    shown = 0.0
    while shown < end - start:
        shown += 0.6
        heard = [w for w in words if w.end <= start + shown]
        if heard:
            tracker.on_words(heard, final=False, replace_from=start)
    tracker.on_words(words, final=True, replace_from=start)
    tracker.on_vad(False, end)
    tracker.on_tick(end + pause)
    return end + pause


def test_interim_decodes_dont_eat_the_opening():
    script, log, events, tracker = make_canary()
    tracker.go_to(2)
    whisper(tracker, "stream reads take fifty six and two hundred fifty four", 10.0)
    take = log.takes[-1]
    assert take.status == COMPLETE and take.sentence == 2
    assert abs(take.start - (10.0 - 0.15)) < 1e-6


def test_opening_word_said_alone_still_starts_the_take():
    script, log, events, tracker = make_canary()
    tracker.go_to(1)
    t = whisper(tracker, "seven", 5.0, pause=0.9)
    whisper(tracker, "days of production traces about one point one five million appends", t)
    take = log.takes[-1]
    assert take.status == COMPLETE and take.sentence == 1
    assert take.start < 5.0
    assert take.words[0].start == 5.0


def test_misheard_opening_word_is_kept_in_the_take():
    script, log, events, tracker = make_canary()
    tracker.go_to(2)
    whisper(tracker, "string reads take fifty six and two hundred fifty four", 20.0)
    assert log.takes[-1].status == COMPLETE
    assert abs(log.takes[-1].start - (20.0 - 0.15)) < 1e-6


def test_restart_folded_into_the_sentence_is_caught():
    script, log, events, tracker = make_canary()
    whisper(tracker, "thirty two different configurations thirty two different configurations three hundred million events per engine", 0.0)
    assert [take.status for take in log.takes] == [REJECTED, COMPLETE]
    assert log.takes[0].reason == "restart"
    assert abs(log.takes[1].start - (1.2 - 0.15)) < 1e-6


def test_restart_from_the_second_word_is_caught():
    script, log, events, tracker = make_canary()
    whisper(tracker, "two different configurations two different configurations three hundred million events per engine", 0.0)
    assert [take.status for take in log.takes] == [REJECTED, COMPLETE]
    assert abs(log.takes[1].start - (0.9 - 0.15)) < 1e-6


def test_words_the_script_repeats_are_not_a_restart():
    script = parse("The log is the truth and the log is the product.", packs.get("en"))
    log = TakeLog()
    tracker = ScriptTracker(script, log, Recorder(), fillers=packs.get("en").fillers)
    whisper(tracker, "the log is the truth and the log is the product", 0.0)
    assert [take.status for take in log.takes] == [COMPLETE]


def test_dropped_opening_word_starts_the_take_where_speech_began():
    script, log, events, tracker = make_canary()
    tracker.go_to(2)
    words, end = tokens("reads take fifty six and two hundred fifty four", 30.6)
    tracker.on_vad(True, 30.0)
    tracker.on_words(words, final=True, replace_from=29.8)
    tracker.on_vad(False, end)
    tracker.on_tick(end + 1.0)
    assert log.takes[-1].status == COMPLETE
    assert abs(log.takes[-1].start - (30.0 - 0.15)) < 1e-6


def test_words_whisper_adds_from_the_prompt_dont_move_the_prompter_ahead():
    script = parse("What does it take to choose where a billion events will live for the next ten years?", packs.get("en"))
    log = TakeLog()
    events = Recorder()
    tracker = ScriptTracker(script, log, events, fillers=packs.get("en").fillers)
    tracker.on_vad(True, 0.0)
    words, _ = tokens("what does it take to choose where a billion next years", 0.0)
    tracker.on_words(words, final=False, replace_from=0.0)
    assert tracker.position == 8
    words, end = tokens("what does it take to choose where a billion events will live for the next ten years", 0.0)
    tracker.on_words(words, final=False, replace_from=0.0)
    assert tracker.position == 16
    tracker.on_words(words, final=True, replace_from=0.0)
    tracker.on_vad(False, end)
    tracker.on_tick(end + 1.0)
    assert log.takes[-1].status == COMPLETE


def test_a_real_skip_is_followed_once_confirmed():
    script = parse("What does it take to choose where a billion events will live for the next ten years?", packs.get("en"))
    log = TakeLog()
    tracker = ScriptTracker(script, log, Recorder(), fillers=packs.get("en").fillers)
    tracker.on_vad(True, 0.0)
    words, _ = tokens("what does it take to live for the next", 0.0)
    tracker.on_words(words, final=False, replace_from=0.0)
    assert tracker.position == 14
