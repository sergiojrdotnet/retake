from pathlib import Path
import json

from retake.edit import exports
from retake.edit.autoedit import Rules, auto_edit
from retake.edit.edl import Edit, History
from retake.session import takes as kinds
from retake.session.takes import COMPLETE, REJECTED, TakeLog, WordTiming


def sample_log():
    log = TakeLog()
    a = log.new_take(0, 1.0, "first"); a.end = 3.0; a.status = COMPLETE
    a.words = [WordTiming(0, "first", 1.1, 1.5)]
    b = log.new_take(1, 4.0, "second"); b.end = 5.5; b.status = REJECTED
    c = log.new_take(1, 6.0, "second"); c.end = 9.0; c.status = COMPLETE; c.score = 60
    c.words = [WordTiming(1, "second", 6.1, 6.6)]
    log.add_marker(kinds.COMMAND, 9.5, 10.2, "again")
    d = log.new_take(2, 11.0, "third take."); d.end = 14.0; d.status = COMPLETE
    d.words = [WordTiming(2, "third", 11.1, 11.5), WordTiming(3, "take.", 11.6, 12.0)]
    log.add_marker(kinds.OFF_SCRIPT, 12.0, 12.4, "um", inside=True)
    log.add_marker(kinds.CHAPTER, 1.0, 1.0, "Intro")
    return log


def test_auto_edit_keeps_last_good_takes():
    edit = auto_edit(sample_log(), 20.0, Rules())
    assert [c.take for c in edit.clips] == [1, 3, 4]
    assert abs(edit.duration - (2.23 + 3.23 + 3.23)) < 0.05


def test_strict_mode_cuts_fillers_inside_sentences():
    edit = auto_edit(sample_log(), 20.0, Rules(extra_speech="strict"))
    assert any(c.end <= 12.0 + 1e-6 for c in edit.clips if c.take == 4)
    assert len([c for c in edit.clips if c.take == 4]) == 2


def test_best_take_option():
    log = sample_log()
    extra = log.new_take(1, 15.0, "second"); extra.end = 16.0; extra.status = COMPLETE; extra.score = 40
    edit = auto_edit(log, 20.0, Rules(keep="best"))
    assert 3 in [c.take for c in edit.clips]


def test_edit_operations_and_undo():
    edit = auto_edit(sample_log(), 20.0, Rules())
    history = History(edit)
    history.checkpoint()
    assert history.edit.split(2.0)
    assert len(history.edit.clips) == 4
    history.checkpoint()
    gap_clip = history.edit.clip_at(2.5)
    history.edit.remove(gap_clip.id)
    assert history.edit.gap_at(2.5) is not None
    assert history.undo() and history.edit.clip_at(2.5) is not None
    assert history.undo() and len(history.edit.clips) == 3
    assert history.redo()


def test_time_mapping_round_trip():
    edit = auto_edit(sample_log(), 20.0, Rules())
    out = edit.to_output(6.5)
    assert out is not None and abs(edit.to_source(out) - 6.5) < 1e-6
    assert edit.to_output(10.0) is None


def test_script_order():
    edit = Edit(source_duration=30, order="script")
    edit.clips = []
    edit.add(10, 12, sentence=0, take=5)
    edit.order = "source"
    edit.add(1, 3, sentence=1, take=2)
    edit.order = "script"
    assert [c.sentence for c in edit.timeline()] == [0, 1]


def test_exports(tmp_path):
    log = sample_log()
    edit = auto_edit(log, 20.0, Rules())
    words = exports.edited_words(log, edit)
    assert [w[2] for w in words] == ["first", "second", "third", "take."]
    vtt = exports.webvtt(words)
    assert vtt.startswith("WEBVTT") and "-->" in vtt
    assert "00:00:00,180 -->" in exports.srt(words)
    assert exports.chapters(log, edit)[0] == (0.0, "Intro")
    labels = exports.audacity_labels(log)
    assert "take 2 s1 rejected" in labels
    from retake.edit.render import Source

    timeline = json.loads(exports.otio(log, edit, [Source(tmp_path / "a.flac", 0.0, 20.0)]))
    clips = timeline["tracks"]["children"][0]["children"]
    assert len(clips) == 3 and clips[0]["media_reference"]["target_url"].startswith("file://")
    meta = exports.ffmetadata([(0.0, "Intro"), (5.0, "Next")], 9.0)
    assert "START=5000" in meta and "END=9000" in meta


def test_script_timing_carries_ids_and_beats():
    from retake.languages import packs
    from retake.script.parser import parse

    script = parse(
        "# Ep\n\n## Scene A\n[[id: scene-a]]\n\n[[b1]] One two. Three four. [[b2]] Five six.\n\n## Scene B\n[[id: scene-b]]\n\nSeven eight.",
        packs.get("en"),
    )
    log = TakeLog()
    for index, (start, end) in enumerate([(1, 2), (3, 4), (5, 6), (7, 8)]):
        take = log.new_take(index, start, script.sentences[index].text)
        take.end, take.status = end, COMPLETE
        take.words = [WordTiming(script.sentences[index].words[0].index, script.sentences[index].words[0].display, start + 0.1, start + 0.4)]
    edit = auto_edit(log, 10.0, Rules())
    timing = exports.script_timing(script, log, edit, "demo")
    assert [s["id"] for s in timing["sections"]] == [None, "scene-a", "scene-b"]
    assert [(b["section_id"], b["beat"], b["sentences"]) for b in timing["beats"]] == [("scene-a", "b1", [0, 1]), ("scene-a", "b2", [2]), ("scene-b", None, [3])]
    first = timing["sentences"][0]
    assert first["output"]["start"] == 0.0 and first["words"][0]["output_start"] is not None
    assert timing["sections"][2]["start"] > timing["sections"][1]["start"]


def test_stage_directions_tables_symbols_and_spoken_forms():
    from retake.languages import packs
    from retake.script.parser import parse

    script = parse(
        "[Cold open] It costs US$ 1,180 → fast.\n\n| a | b |\n|---|---|\n\n{zstd|=zee standard} wins (really).",
        packs.get("en"),
    )
    kinds = [t.kind for t in script.sentences[0].tokens]
    assert kinds[0] == "cue" and "text" in kinds
    assert ["one", "thousand", "one", "hundred", "eighty"] in [w.variants for w in script.words if w.display == "1,180"][0]
    assert all("|" not in s.display_text for s in script.sentences)
    zstd = next(w for w in script.words if w.display == "zstd")
    assert zstd.variants == [["zee", "standard"]] and zstd.spoken == "zee standard"
    assert script.sentences[-1].words[-1].display == "(really)."


def test_video_cuts_follow_the_output_frame_grid():
    from retake.edit.render import frame_aligned

    segments = [(i * 7.0, i * 7.0 + 5.23) for i in range(228)]
    aligned = frame_aligned(segments, 30.0)
    assert all(abs((end - start) * 30 - round((end - start) * 30)) < 1e-6 for start, end in aligned)
    assert abs(sum(end - start for start, end in aligned) - 228 * 5.23) < 1 / 60
    assert all(a[0] == s[0] for a, s in zip(aligned, segments))


def test_render_reads_each_piece_from_its_own_recording(tmp_path):
    import numpy as np
    import soundfile as sf

    from retake.edit import media
    from retake.edit.render import RenderJob, Source, pieces, render

    rate = 48000
    sf.write(tmp_path / "part-001.flac", np.full(rate * 2, 0.1, dtype=np.float32), rate, subtype="PCM_24")
    sf.write(tmp_path / "part-002.flac", np.full(rate * 1, -0.1, dtype=np.float32), rate, subtype="PCM_24")
    sources = [Source(tmp_path / "part-001.flac", 0.0, 2.0), Source(tmp_path / "part-002.flac", 2.0, 1.0)]
    edit = Edit(source_duration=3.0, order="script", crossfade_ms=0)
    edit.add(0.5, 1.0, sentence=0)
    edit.add(1.5, 2.5, sentence=1)
    edit.add(2.6, 2.9, sentence=2)
    job = RenderJob(edit, sources, tmp_path / "out.flac")
    planned = pieces(job)
    assert [(p.source.audio.name, round(p.local, 3), round(p.duration, 3)) for p in planned] == [
        ("part-001.flac", 0.5, 0.5), ("part-001.flac", 1.5, 0.5), ("part-002.flac", 0.0, 0.5), ("part-002.flac", 0.6, 0.3)]
    render(job)
    assert abs(media.probe(tmp_path / "out.flac").duration - 1.8) < 0.01


def test_pickups_replace_only_their_sentences_and_keep_hand_edits():
    from retake.edit.autoedit import update_sentences

    log = TakeLog()
    for sentence, start in [(0, 1.0), (1, 4.0), (2, 7.0)]:
        take = log.new_take(sentence, start, f"s{sentence}")
        take.end, take.status = start + 2.0, COMPLETE
    edit = auto_edit(log, 10.0, Rules(order="script"), boundaries=[])
    edit.split(8.0)
    pickup = log.new_take(1, 12.0, "s1")
    pickup.end, pickup.status = 13.5, COMPLETE
    edit.source_duration = 14.0
    assert update_sentences(edit, log, {1}, Rules(order="script"), 14.0, boundaries=[10.0]) == [1]
    sentence_one = [c for c in edit.clips if c.sentence == 1]
    assert len(sentence_one) == 1 and sentence_one[0].start >= 10.0 and sentence_one[0].take == pickup.id
    assert len([c for c in edit.clips if c.sentence == 2]) == 2
    assert [c.sentence for c in edit.timeline()] == [0, 1, 2, 2]


def test_auto_edit_handles_stop_at_part_boundaries():
    log = TakeLog()
    take = log.new_take(0, 9.95, "s0")
    take.end, take.status = 10.0 - 0.01, COMPLETE
    second = log.new_take(1, 10.02, "s1")
    second.end, second.status = 11.0, COMPLETE
    edit = auto_edit(log, 12.0, Rules(), boundaries=[10.0])
    first, last = sorted(edit.clips, key=lambda c: c.start)
    assert first.end <= 10.0 and last.start >= 10.0


def test_phone_recorder_starts_and_stops_scrcpy(tmp_path, monkeypatch):
    import os
    import stat

    from retake.video import phone

    fake = tmp_path / "bin" / "scrcpy"
    fake.parent.mkdir()
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import signal, sys, time\n"
        "out = [a.split('=', 1)[1] for a in sys.argv if a.startswith('--record=')][0]\n"
        "print('INFO: Recording started to mkv file: ' + out, flush=True)\n"
        "def stop(*_):\n"
        "    open(out, 'wb').write(b'mkv')\n"
        "    print('INFO: Recording complete', flush=True)\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGINT, stop)\n"
        "time.sleep(30)\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{fake.parent}{os.pathsep}{os.environ['PATH']}")
    args = phone.command(tmp_path / "part-001.mkv", {"phone_camera": "front", "phone_size": "3840x2160", "phone_preview": False, "phone_shape": "portrait"})
    assert "--camera-facing=front" in args and "--camera-size=3840x2160" in args and "--no-window" in args
    assert "--capture-orientation=270" in args and "--audio-source=mic" in args and "--video-codec=h265" in args
    assert phone.capture_rotation({"phone_shape": "portrait", "phone_camera": "back"}) == 90
    assert phone.capture_rotation({"phone_shape": "landscape", "phone_flip": True}) == 180
    assert not any(a.startswith("--capture-orientation") for a in phone.command(tmp_path / "x.mkv", {}))
    assert "--camera-id=2" in phone.command(tmp_path / "x.mkv", {"phone_camera": "2"})
    recorder = phone.PhoneRecorder(tmp_path / "part-001.mkv", {"phone_preview": False}, tmp_path / "scrcpy.log")
    recorder.start(timeout=10)
    assert recorder.started is not None
    assert recorder.stop() == tmp_path / "part-001.mkv"
    assert "Recording complete" in (tmp_path / "scrcpy.log").read_text()


def test_phone_recorder_reports_scrcpy_errors(tmp_path, monkeypatch):
    import os
    import stat

    import pytest

    from retake.video import phone

    fake = tmp_path / "bin" / "scrcpy"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\necho 'ERROR: Could not find any ADB device'\nexit 1\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{fake.parent}{os.pathsep}{os.environ['PATH']}")
    recorder = phone.PhoneRecorder(tmp_path / "part-001.mkv", {}, tmp_path / "scrcpy.log")
    with pytest.raises(RuntimeError, match="Could not find any ADB device"):
        recorder.start(timeout=5)


def test_phone_preview_feeds_the_virtual_camera_without_recording(tmp_path):
    from retake.video import phone

    preview = phone.command(None, {"phone_size": "3840x2160"}, "/dev/video42")
    assert "--v4l2-sink=/dev/video42" in preview and "--no-audio" in preview and "--max-size=1280" in preview
    assert not any(a.startswith("--record") or a.startswith("--camera-size") for a in preview)
    both = phone.command(tmp_path / "part-001.mkv", {}, "/dev/video42")
    assert "--v4l2-sink=/dev/video42" in both and any(a.startswith("--record=") for a in both) and "--no-window" in both
    for settings, sink in [({}, "/dev/video42"), ({"phone_preview": True}, None), ({"phone_preview": False}, None)]:
        assert "--no-audio-playback" in phone.command(tmp_path / "part.mkv", settings, sink)


def test_phone_cameras_are_read_from_scrcpy_and_settings_fit_them():
    from retake.video import phone

    sample = (
        "    --camera-id=0    (back, 4096x3072, fps={14, 20, 24, 30}, zoom-range=[1, 10])\n"
        "        - 4096x3072\n        - 3840x2160\n        - 1920x1080\n"
        "      High speed capture (--camera-high-speed):\n"
        "        - 1280x720 (fps={120, 240})\n        - 1920x1080 (fps={120, 240})\n"
        "    --camera-id=1    (front, 2592x1944, fps={10, 15, 20, 24, 30}, zoom-range=[1, 10])\n"
        "        - 2592x1944\n        - 1920x1080\n"
    )
    cameras = phone.parse_cameras(sample)
    assert [(c.id, c.facing, max(c.fps)) for c in cameras] == [("0", "back", 30), ("1", "front", 30)]
    options, note = phone.resolve({"phone_camera": "back", "phone_fps": 60}, cameras)
    assert options["phone_fps"] == 30 and "60" in note
    options, note = phone.resolve({"phone_camera": "0", "phone_fps": 120, "phone_size": "3840x2160"}, cameras)
    assert options["phone_high_speed"] and options["phone_size"] == "1920x1080"
    assert "--camera-high-speed" in phone.command(Path("x.mkv"), options)
    options, _ = phone.resolve({"phone_camera": "front", "phone_size": "3840x2160", "phone_shape": "portrait"}, cameras)
    assert options["phone_size"] == "1920x1080" and phone.capture_rotation(options) == 270


def test_trimming_drops_the_wait_and_pauses_and_keeps_sync(tmp_path):
    import subprocess

    import numpy as np

    from retake.edit import media, trim

    video = tmp_path / "part.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=30",
                    "-c:v", "libx264", "-g", "30", "-pix_fmt", "yuv420p", str(video)], check=True)
    original = tmp_path / "original.mkv"
    original.write_bytes(video.read_bytes())

    def frame(path, at):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                             capture_output=True, check=True).stdout
        return np.frombuffer(raw, dtype=np.uint8).astype(float)

    segments = trim.trim(video, audio_duration=22.0, offset=-5.0, pauses=[(8.0, 14.0)])
    assert [(s.audio_start, s.audio_end, round(s.offset, 3)) for s in segments] == [(0.0, 9.0, 0.0), (13.0, 22.0, 4.0)]
    assert abs(media.probe(video).duration - 18.0) < 0.2
    for t in (0.5, 4.0, 8.5, 13.5, 20.0):
        moved = t - trim.offset_at(segments, -5.0, t)
        assert np.abs(frame(original, t + 5.0) - frame(video, moved)).mean() < 2.0, t


def test_render_follows_the_time_map_of_trimmed_video(tmp_path):
    from retake.edit.render import RenderJob, Source, VideoInfo, build_inputs, pieces
    from retake.edit.trim import Segment

    video = tmp_path / "part.mkv"
    source = Source(tmp_path / "part.flac", 0.0, 22.0, video, -5.0, [Segment(0.0, 9.0, 0.0), Segment(13.0, 22.0, 4.0)])
    edit = Edit(source_duration=22.0, order="script", crossfade_ms=0)
    edit.add(2.0, 4.0, sentence=0)
    edit.add(8.0, 15.0, sentence=1)
    job = RenderJob(edit, [source], tmp_path / "out.mp4", with_video=True)
    planned = pieces(job)
    assert [(round(p.local, 3), round(p.duration, 3)) for p in planned] == [(2.0, 2.0), (8.0, 1.0), (9.0, 6.0)]
    inputs, _ = build_inputs(job, planned, VideoInfo({video: 18.0}))
    video_seeks = [inputs[i + 1] for i in range(len(inputs)) if inputs[i] == "-ss" and inputs[i + 5] == str(video)]
    assert video_seeks == ["2.0000", "8.0000", "5.0000"]


def test_phone_video_is_moved_to_the_audio_with_keyframed_sound(tmp_path):
    import subprocess

    from retake.edit import media

    clip = tmp_path / "clip.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=4", "-f", "lavfi", "-i", "sine=duration=4",
                    "-c:v", "libx264", "-c:a", "aac", str(clip)], check=True)
    shifted = tmp_path / "phone.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-itsoffset", "500000", "-i", str(clip), "-i", str(clip), "-map", "0:v", "-map", "1:a", "-c", "copy", str(shifted)], check=True)
    assert media.first_timestamp(shifted, "v:0") > 400000
    media.prepare_phone_video(shifted)
    assert abs(media.first_timestamp(shifted, "v:0")) < 0.1 and abs(media.probe(shifted).duration - 4.0) < 0.2
    flags = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "packet=flags", "-of", "csv=p=0", str(shifted)],
                           capture_output=True, text=True, check=True).stdout.split()
    assert flags and all("K" in f for f in flags), "every audio packet must be a keyframe"


def test_offset_comes_from_the_soundtracks_even_across_a_pause(tmp_path):
    import numpy as np
    import soundfile as sf

    from retake.edit import media

    rate = 48000
    rng = np.random.default_rng(3)
    speech = (rng.standard_normal(rate * 60) * 0.2).astype(np.float32)
    speech[rate * 10:rate * 30] = 0.0
    sf.write(tmp_path / "master.flac", speech, rate)
    delay = 1.55
    phone = speech[int(delay * rate):] * 0.3 + rng.standard_normal(len(speech) - int(delay * rate)).astype(np.float32) * 0.01
    sf.write(tmp_path / "phone.wav", phone, rate)
    offset, method = media.estimate_offset(tmp_path / "master.flac", tmp_path / "phone.wav", 100.0, video_t0=101.42)
    assert method == "correlation" and abs(offset - delay) < 0.01
