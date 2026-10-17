from pathlib import Path

from retake.languages import packs
from retake.script.parser import parse
from retake.session import takes as kinds
from retake.session.coach import detect_patterns
from retake.session.free import FreeTracker, is_retry
from retake.session.session import FREE, Session, SessionSettings
from retake.session.takes import COMPLETE, REJECTED, TakeLog


class Listener:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append((name, args))

    def requests(self, kind):
        return [args[0] for name, args in self.calls if name == "request" and args[0]["type"] == kind]


def words(text, start, step=0.3):
    out = []
    t = start
    for w in text.split():
        out.append({"text": w, "start": t, "end": t + step * 0.8})
        t += step
    return out, t


def say(session, text, start):
    tokens, end = words(text, start)
    session.on_engine({"type": "vad", "speech": True, "time": start})
    session.on_engine({"type": "words", "final": True, "words": tokens})
    session.on_engine({"type": "progress", "time": end + 0.5})
    session.on_engine({"type": "vad", "speech": False, "time": end})
    session.tick(end + 0.6)
    return end + 0.8


def scripted():
    script = parse("# Intro\n\nWe flush the cache to disk. Then we measure latency.", packs.get("en"))
    listener = Listener()
    session = Session(TakeLog(), SessionSettings(), listener, script, packs.get("en"), packs.get("pt-BR"))
    session.start()
    return session, listener


def test_scripted_session_scores_and_chapters():
    session, listener = scripted()
    t = say(session, "we flush the cache to disk", 0.0)
    assert session.log.takes[0].status == COMPLETE
    assert listener.requests("score") and listener.requests("score")[0]["words"][0]["text"] == "We"
    assert [m.label for m in session.log.markers_of(kinds.CHAPTER)] == ["Intro"]
    assert listener.requests("context")[-1]["text"].startswith("Then")


def test_voice_again_after_sentence_redoes_it():
    session, listener = scripted()
    t = say(session, "we flush the cache to disk", 0.0)
    session.on_engine({"type": "command", "action": "again", "start": t, "end": t + 0.8, "phrase": "retake again"})
    session.on_engine({"type": "progress", "time": t + 2})
    assert session.log.takes[0].status == REJECTED
    assert session.tracker.sentence == 0
    say(session, "we flush the cache to disk", t + 2)
    assert [t.status for t in session.log.takes] == [REJECTED, COMPLETE]


def test_command_waits_for_tracking_progress():
    session, listener = scripted()
    session.on_engine({"type": "command", "action": "again", "start": 2.0, "end": 2.6})
    assert session.pending_commands
    session.on_engine({"type": "progress", "time": 1.0})
    assert session.pending_commands
    session.on_engine({"type": "progress", "time": 3.0})
    assert not session.pending_commands


def test_coach_feedback_flags_low_scores():
    session, listener = scripted()
    say(session, "we flush the cache to disk", 0.0)
    request = listener.requests("score")[0]
    scores = [{"score": 90, "expected": "", "heard": ""} for _ in request["words"]]
    scores[3] = {"score": 30, "expected": "kæʃ", "heard": "kɛʃ"}
    session.on_engine({"type": "score", "request": request["request"], "words": scores})
    feedback = [args for name, args in listener.calls if name == "coach_feedback"]
    assert feedback and feedback[-1][1][0]["text"] == "cache"


def score_take(session, listener, low_word=3, low=20.0, others=90.0):
    request = listener.requests("score")[-1]
    scores = [{"score": others, "expected": "", "heard": ""} for _ in request["words"]]
    scores[low_word] = {"score": low, "expected": "kæʃ", "heard": "kɛʃ"}
    session.on_engine({"type": "score", "request": request["request"], "words": scores})


def test_require_level_sends_back_without_the_drill():
    session, listener = scripted()
    session.settings.coach.require = 40
    session.settings.coach.drill = False
    say(session, "we flush the cache to disk", 0.0)
    score_take(session, listener)
    assert session.log.takes[0].status == REJECTED
    assert session.tracker.sentence == 0
    assert ("notice", ("retake", "coach")) in listener.calls
    assert ("drill_changed", ({},)) not in listener.calls


def test_a_word_between_the_levels_only_warns():
    session, listener = scripted()
    session.settings.coach.require = 40
    say(session, "we flush the cache to disk", 0.0)
    score_take(session, listener, low=48)
    assert session.log.takes[0].status == COMPLETE
    assert session.drill is None
    assert [args for name, args in listener.calls if name == "marks_changed"][-1] == ([], [3]), "warned words turn yellow"


def attempt(session, listener, start, score):
    session.on_engine({"type": "vad", "speech": True, "time": start})
    session.on_engine({"type": "vad", "speech": False, "time": start + 0.5})
    request = listener.requests("score")[-1]
    assert request["take"] is None and request["words"][0]["text"] == "cache"
    session.on_engine({"type": "score", "request": request["request"], "words": [{"score": score, "expected": "kæʃ", "heard": ""}]})
    return start + 1.0


def voice_done(session, at):
    session.tts_played(at, at + 0.6, "cache")
    return at + 1.0


def test_drill_needs_the_word_right_several_times_in_a_row_then_rereads_the_sentence():
    session, listener = scripted()
    session.settings.coach.require = 40
    session.settings.coach.drill_times = 2
    t = say(session, "we flush the cache to disk", 0.0)
    score_take(session, listener)
    assert session.log.takes[0].status == REJECTED
    assert session.drill is not None and session.tracker.paused
    assert listener.requests("tts")[-1]["text"] == "cache"
    assert [args for name, args in listener.calls if name == "marks_changed"][-1] == ([3], [])
    t = voice_done(session, t)
    t = attempt(session, listener, t, 70)
    assert session.drill.passes == 1
    t = voice_done(session, t)
    t = attempt(session, listener, t, 30)
    assert session.drill.passes == 0, "a miss starts the count again"
    for _ in range(2):
        t = voice_done(session, t)
        t = attempt(session, listener, t, 80)
    assert session.drill is None and not session.tracker.paused
    assert session.tracker.sentence == 0 and session.tracker.position == -1
    assert session.log.takes[0].flagged[0]["drill"] == "passed"
    drill = session.log.markers_of(kinds.DRILL)
    assert drill and drill[0].end > drill[0].start
    say(session, "we flush the cache to disk", t)
    score_take(session, listener, low=80)
    assert [args for name, args in listener.calls if name == "marks_changed"][-1] == ([], [])


def test_speech_during_the_reference_voice_is_not_an_attempt():
    session, listener = scripted()
    session.settings.coach.require = 40
    t = say(session, "we flush the cache to disk", 0.0)
    score_take(session, listener)
    before = len(listener.requests("score"))
    session.on_engine({"type": "vad", "speech": True, "time": t})
    session.on_engine({"type": "vad", "speech": False, "time": t + 0.5})
    assert len(listener.requests("score")) == before


def test_skip_and_uncoach_move_on_and_uncoached_words_are_never_scored():
    session, listener = scripted()
    session.settings.coach.require = 40
    say(session, "we flush the cache to disk", 0.0)
    score_take(session, listener)
    session.handle("skip")
    assert session.drill is None and session.log.takes[0].flagged[0]["drill"] == "skipped"
    t = say(session, "we flush the cache to disk", 5.0)
    score_take(session, listener)
    session.handle("uncoach")
    assert "cache" in session.history.uncoached() and session.drill is None
    say(session, "we flush the cache to disk", t + 2)
    score_take(session, listener)
    assert session.log.takes[-1].status == COMPLETE and session.log.takes[-1].flagged == []


def test_pausing_ends_the_drill():
    session, listener = scripted()
    session.settings.coach.require = 40
    say(session, "we flush the cache to disk", 0.0)
    score_take(session, listener)
    session.handle("pause")
    assert session.drill is None and session.tracker.paused
    session.handle("resume")
    assert not session.tracker.paused and session.tracker.sentence == 0


def test_pause_marks_and_resumes():
    session, listener = scripted()
    session.handle("pause", time=1.0)
    session.now = 3.0
    session.handle("resume", time=3.0)
    pause = session.log.markers_of(kinds.PAUSE)[0]
    assert (pause.start, pause.end) == (1.0, 3.0)
    assert session.state == "listening"


def test_free_session_detects_restarts_and_fillers():
    listener = Listener()
    log = TakeLog()
    session = Session(log, SessionSettings(mode=FREE), listener, None, packs.get("en"))
    session.start()
    t = say(session, "the event store keeps every change", 0.0)
    t = say(session, "the event store keeps every single change", t)
    t = say(session, "um uh", t)
    assert [take.status for take in log.takes] == [REJECTED, COMPLETE]
    assert log.markers_of(kinds.FILLER)


def test_retry_similarity():
    assert is_retry("we flush the cache to disk", "we flush the cache to the disk")
    assert not is_retry("we flush the cache to disk", "latency matters a lot here")


def test_l1_patterns():
    catalog = packs.get("pt-BR").l1_errors
    assert "vowel-length" in [e.id for e in detect_patterns("biːtʃ", "bɪtʃ", catalog)]
    assert "th-stopping" in [e.id for e in detect_patterns("θɪŋk", "tɪŋk", catalog)]
    assert "epenthesis" in [e.id for e in detect_patterns("bɪɡ", "bɪɡi", catalog)]


def test_whisper_style_words_are_normalized():
    script = parse("Today we compare the 2026 results.", packs.get("en"))
    listener = Listener()
    session = Session(TakeLog(), SessionSettings(), listener, script, packs.get("en"))
    session.start()
    words = [{"text": t, "start": i * 0.4, "end": i * 0.4 + 0.3} for i, t in enumerate(["Today", "we", "compare", "the", "2026", "results."])]
    session.on_engine({"type": "vad", "speech": True, "time": 0.0})
    session.on_engine({"type": "words", "final": True, "replace_from": 0.0, "words": words})
    session.on_engine({"type": "vad", "speech": False, "time": 2.4})
    session.tick(3.2)
    take = session.log.takes[0]
    assert take.status == COMPLETE and not take.deviations


def test_session_starts_where_the_prompter_is():
    script = parse("# Intro\n\nOne two three. Four five six. Seven eight nine.", packs.get("en"))
    listener = Listener()
    session = Session(TakeLog(), SessionSettings(), listener, script, packs.get("en"), start_sentence=1)
    session.start()
    say(session, "four five six", 0.0)
    assert [(t.sentence, t.status) for t in session.log.takes] == [(1, COMPLETE)]


def test_lexicon_sets_the_reading_and_inline_overrides_win(tmp_path):
    from retake.phonetics.guides import GuideBuilder
    from retake.script.lexicon import Lexicon

    script_file = tmp_path / "talk.md"
    script_file.write_text("We read logs. Yesterday we {read|rɛd} more.")
    (tmp_path / "talk.lexicon.tsv").write_text("read\triːd\t\t\n")
    lexicon = Lexicon.for_script(script_file)
    script = parse(script_file.read_text(), packs.get("en"))
    book = GuideBuilder(packs.get("en"), packs.get("pt-BR"), lexicon).build(script)
    first, second = [w for w in script.words if w.key == "read"]
    assert (book.for_word(first).source, book.for_word(first).ipa) == ("lexicon", "/ˈrid/")
    assert (book.for_word(second).source, book.for_word(second).ipa) == ("override", "/ˈrɛd/")
    listener = Listener()
    session = Session(TakeLog(), SessionSettings(), listener, script, packs.get("en"), lexicon=lexicon)
    session.start()
    t = say(session, "we read logs", 0.0)
    say(session, "yesterday we read more", t)
    overrides = [w["override"] for r in listener.requests("score") for w in r["words"] if w["text"] == "read"]
    assert overrides == ["riːd", "rɛd"]


def test_sound_cues_follow_state_and_notices():
    from retake.ui.sounds import cue_for_notice, cue_for_state

    assert [cue_for_state(a, b) for a, b in [("ready", "listening"), ("listening", "paused"), ("paused", "listening"), ("paused", "stopped"), ("listening", "listening")]] == ["start", "pause", "start", "stop", None]
    assert [cue_for_notice(k, t) for k, t in [("retake", "coach"), ("command", "again"), ("command", "pause"), ("end", ""), ("off-script", "um")]] == ["retake", "command", None, "end", None]


def test_accented_wake_word_is_found_in_the_transcript():
    from retake.engine.commands import CommandGate, TranscriptCommands

    finder = TranscriptCommands(packs.get("en"), "retake", ["he take", "he'd take"])
    heard = [{"text": t, "start": i * 0.3, "end": i * 0.3 + 0.25, "conf": 0.9} for i, t in enumerate(["latency.", "He'd", "take", "again."])]
    events = finder.find(heard)
    assert [(e["action"], e["phrase"]) for e in events] == [("again", "he'd take again")]
    assert finder.find([{"text": t, "start": 0, "end": 0.2} for t in ["Retake,", "how", "do", "I", "say", "idempotent?"]])[0]["arg"] == "idempotent"
    gate = CommandGate()
    assert gate.admit(events[0]) and not gate.admit(dict(events[0], start=events[0]["start"] + 0.5))


def test_native_pack_adds_wake_aliases():
    from retake import config as config_module
    from retake.engine import settings

    config = config_module.load(Path("/nonexistent"))
    assert "he'd take" in settings.build(config, check_gpu=False)["wake_aliases"]


def test_pickup_session_walks_only_the_queued_sentences():
    script = parse("# Intro\n\nOne two three. Four five six. Seven eight nine. Ten eleven twelve.", packs.get("en"))
    listener = Listener()
    session = Session(TakeLog(), SessionSettings(), listener, script, packs.get("en"), pickup=[1, 3])
    session.start()
    assert session.tracker.sentence == 1
    t = say(session, "four five six", 0.0)
    assert session.tracker.sentence == 3
    say(session, "ten eleven twelve", t)
    assert [(tk.sentence, tk.status) for tk in session.log.takes] == [(1, COMPLETE), (3, COMPLETE)]
    assert ("notice", ("pickups-done", "")) in listener.calls


def test_lexicon_coach_column_and_personal_list(tmp_path):
    from retake.script.lexicon import Lexicon
    from retake.session.coach import PracticeHistory

    path = tmp_path / "ep1.lexicon.tsv"
    path.write_text("# word\tipa\tflagged\tspoken\tcoach\nsergio\t\t\t\toff\nkubernetes\tˌkubɚˈnɛtiz\t\t\t\n", encoding="utf-8")
    lexicon = Lexicon.load(path)
    assert lexicon.uncoached("sergio") and not lexicon.uncoached("kubernetes")
    lexicon.set_flag("kubernetes", True)
    assert Lexicon.load(path).uncoached("sergio"), "saving keeps the coach column"
    history = PracticeHistory(tmp_path / "practice.json")
    history.set_coached("acme", False)
    history.save()
    assert PracticeHistory.load(tmp_path / "practice.json").uncoached() == {"acme"}
    history.set_coached("acme", True)
    assert history.uncoached() == set()


def test_piper_says_the_given_ipa_in_its_own_symbols(tmp_path):
    import json

    from retake.engine.tts import PiperVoice

    model = tmp_path / "voice.onnx"
    symbols = {ch: [i] for i, ch in enumerate("lɪvaɪnsɜːtˈ ")}
    (tmp_path / "voice.onnx.json").write_text(json.dumps({"audio": {"sample_rate": 22050}, "phoneme_id_map": symbols}), encoding="utf-8")
    voice = PiperVoice(model, binary="piper")
    assert voice.phonemes("/lˈɪv/") == "lˈɪv"
    assert voice.phonemes("ˈɪnsɝts") == "ˈɪnsɜːts", "ɝ is spelled the way the voice knows it"
    assert voice.phonemes("lɪv|laɪv") == "lɪv"
    assert voice.phonemes("ʒʒ") == ""


def test_drill_on_demand_takes_the_warned_words_of_this_or_the_previous_sentence():
    session, listener = scripted()
    session.settings.coach.require = 30
    t = say(session, "we flush the cache to disk", 0.0)
    request = listener.requests("score")[-1]
    scores = [{"score": 90, "expected": "", "heard": ""} for _ in request["words"]]
    scores[1] = {"score": 45, "expected": "flʌʃ", "heard": ""}
    scores[3] = {"score": 50, "expected": "kæʃ", "heard": ""}
    session.on_engine({"type": "score", "request": request["request"], "words": scores})
    assert session.log.takes[0].status == COMPLETE and session.drill is None
    assert session.tracker.sentence == 1, "the take passed, so the prompter moved on"
    session.handle("drill")
    assert session.drill is not None and [w.text for w in session.drill.words] == ["flush", "cache"]
    assert session.log.takes[0].status == REJECTED and session.log.takes[0].reason == "drill"
    assert session.tracker.sentence == 0
    session.handle("skip")
    session.handle("skip")
    assert session.drill is None and session.tracker.sentence == 0 and session.tracker.position == -1


def test_drill_on_demand_with_nothing_warned_says_so():
    session, listener = scripted()
    session.handle("drill")
    assert session.drill is None and ("notice", ("drill-none", "")) in listener.calls


def test_a_voice_command_during_a_drill_is_not_a_try():
    session, listener = scripted()
    session.settings.coach.require = 40
    t = say(session, "we flush the cache to disk", 0.0)
    score_take(session, listener)
    t = voice_done(session, t)
    session.on_engine({"type": "vad", "speech": True, "time": t})
    session.on_engine({"type": "vad", "speech": False, "time": t + 1.2})
    request = listener.requests("score")[-1]
    session.on_engine({"type": "score", "request": request["request"], "words": [{"score": 10, "expected": "kæʃ", "heard": ""}]})
    session.on_engine({"type": "command", "action": "listen", "start": t, "end": t + 1.2})
    session.on_engine({"type": "progress", "time": t + 3})
    session.tick(t + 2.5)
    assert session.drill.attempts == 0 and session.drill.passes == 0
