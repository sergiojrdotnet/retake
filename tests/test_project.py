import numpy as np
import pytest
import soundfile as sf

from retake import project as projects
from retake.languages import packs
from retake.script.parser import parse
from retake.session.takes import COMPLETE, REJECTED, TakeLog, WordTiming


def tone(path, seconds):
    sf.write(path, np.zeros(int(16000 * seconds), dtype=np.float32), 16000, subtype="PCM_24")


def test_project_imports_scripts_and_lines_up_parts(tmp_path):
    source = tmp_path / "screenplay" / "ep1.md"
    source.parent.mkdir()
    source.write_text("# Ep 1\n\nOne two three. Four five six.")
    source.with_name("ep1.lexicon.tsv").write_text("word\tipa\n")
    project = projects.Project.create(tmp_path / "Event Store Course", "Event Store Course")
    assert project.path.name == "Event Store Course.retake"
    item = project.add_script(source, "Episode 1")
    assert (project.directory / "scripts" / "ep1.md").read_text() == source.read_text()
    assert (project.directory / "scripts" / "ep1.lexicon.tsv").exists()
    again = project.add_script(source)
    assert again.id == "ep1-2"

    index, audio = item.next_part()
    assert audio.name == "part-001.flac"
    tone(audio, 2.0)
    item.add_part(index, audio, 2.0)
    index, audio = item.next_part()
    tone(audio, 1.5)
    item.add_part(index, audio, 1.5, kind="pickup", sentences=[1])

    reloaded = projects.Project.load(project.path)
    parts = reloaded.item("ep1").parts
    assert [(p.index, p.start, p.duration, p.kind) for p in parts] == [(1, 0.0, 2.0, "recording"), (2, 2.0, 1.5, "pickup")]
    assert reloaded.item("ep1").part_at(2.5).index == 2 and reloaded.item("ep1").boundaries() == [2.0]
    assert reloaded.find_by_source(source).id == "ep1"
    assert projects.items_for_source(tmp_path, source)[0][1].id == "ep1"


def test_merging_a_part_moves_takes_onto_the_item_timeline(tmp_path):
    saved = []
    item_log = TakeLog(saved.append)
    first = item_log.new_take(0, 1.0, "One two three.")
    first.end, first.status = 2.0, COMPLETE
    part = TakeLog()
    redo = part.new_take(0, 0.5, "One two three.")
    redo.end, redo.status = 1.4, COMPLETE
    redo.words = [WordTiming(0, "One", 0.6, 0.8)]
    part.add_marker("command", 1.5, 1.9, "again")
    added = projects.merge_takes(item_log, part, 10.0)
    assert (added[0].id, added[0].number, added[0].start, added[0].words[0].start) == (2, 2, 10.5, 10.6)
    assert item_log.markers[0].start == 11.5
    assert saved[-1]["takes"][1]["start"] == 10.5


def test_edited_scripts_keep_takes_on_the_right_sentence(tmp_path):
    project = projects.Project.create(tmp_path / "P", "P")
    source = tmp_path / "ep.md"
    source.write_text("One two. Three four. Five six.")
    item = project.add_script(source)
    old = parse(source.read_text(), packs.get("en"))
    new = parse("Zero. One two. Five six.", packs.get("en"))
    log = item.load_takes()
    for sentence in (0, 1, 2):
        take = log.new_take(sentence, sentence * 2.0, old.sentences[sentence].text)
        take.end, take.status = sentence * 2.0 + 1, COMPLETE
    log.save()
    result = projects.remap_item(item, old, new)
    assert (result.reworded, result.lost) == ([], 1)
    takes = item.load_takes().takes
    assert [(t.sentence, t.status) for t in takes] == [(1, COMPLETE), (None, REJECTED), (2, COMPLETE)]


def test_reworded_sentences_keep_their_takes_as_stale(tmp_path):
    from retake.edit.autoedit import Rules, auto_edit

    project = projects.Project.create(tmp_path / "P", "P")
    source = tmp_path / "ep.md"
    source.write_text("We store events in one log. Reads come later. The end.")
    item = project.add_script(source)
    old = parse(source.read_text(), packs.get("en"))
    new = parse("We store all the events in one log. Reads come much later. The end.", packs.get("en"))
    log = item.load_takes()
    for sentence in (0, 1, 2):
        take = log.new_take(sentence, sentence * 3.0, old.sentences[sentence].text)
        take.end, take.status = sentence * 3.0 + 2, COMPLETE
    log.save()
    result = projects.remap_item(item, old, new)
    assert (result.reworded, result.lost) == ([0, 1], 0)
    log = item.load_takes()
    assert [(t.sentence, t.stale) for t in log.takes] == [(0, True), (1, True), (2, False)]
    fresh = log.new_take(0, 10.0, new.sentences[0].text)
    fresh.end, fresh.status, fresh.score = 12.0, COMPLETE, 10.0
    stale_best = log.takes[0]
    stale_best.score = 99.0
    edit = auto_edit(log, 13.0, Rules(keep="best"))
    assert next(c.take for c in edit.clips if c.sentence == 0) == fresh.id


def test_crashed_parts_are_recovered(tmp_path):
    project = projects.Project.create(tmp_path / "P", "P")
    source = tmp_path / "ep.md"
    source.write_text("One two.")
    item = project.add_script(source)
    tone(item.folder / "part-001.flac", 2.0)
    (item.folder / "part-001.mkv").write_bytes(b"video")
    item.recording_log(1).new_take(None, 0.5, "hello")
    project.close()
    reopened = projects.Project.load(project.path)
    item = reopened.items[0]
    assert projects.recover_parts(item) == [1]
    assert item.parts[0].kind == "recovered" and item.parts[0].video.name == "part-001.mkv"
    assert item.load_takes().takes[0].start == 0.5 and item.unfinished_recording(1) is None


def test_everything_but_the_media_lives_in_the_project_file(tmp_path):
    from retake.edit.edl import Edit

    project = projects.Project.create(tmp_path / "P", "P")
    source = tmp_path / "ep.md"
    source.write_text("One two. Three four.")
    item = project.add_script(source)
    assert projects.sync_script(item) is None and item.snapshot == "One two. Three four."
    log = item.load_takes()
    log.new_take(0, 1.0, "One two.")
    edit = Edit(source_duration=3.0)
    edit.add(1.0, 2.0, sentence=0, take=1)
    item.save_edit(edit)
    project.close()
    item = projects.Project.load(project.path).item("ep")
    assert item.load_takes().takes[0].text == "One two." and item.load_edit().clips[0].take == 1
    assert sorted(p.name for p in (tmp_path / "P").iterdir()) == ["P.retake", "ep", "scripts"]
    assert list(item.folder.iterdir()) == []
    item.project.remove_item("ep")
    assert item.project.store.log("ep") is None and item.project.store.snapshot("ep") is None


def test_other_files_are_not_projects(tmp_path):
    fake = tmp_path / "old.retake"
    fake.write_text('{"format": "retake-project"}')
    with pytest.raises(ValueError, match="not a Retake project"):
        projects.Project.load(fake)


def test_projects_outside_the_projects_folder_are_found_through_recents(tmp_path):
    source = tmp_path / "ep1.md"
    source.write_text("One two.")
    away = projects.Project.create(tmp_path / "drive" / "Course", "Course")
    away.add_script(source)
    base = tmp_path / "projects"
    base.mkdir()
    assert projects.items_for_source(base, source) == []
    found = projects.items_for_source(base, source, [str(away.path)])
    assert [(p.title, i.id) for p, i in found] == [("Course", "ep1")]
    assert [row["title"] for row in projects.list_projects(base, [str(away.path), str(tmp_path / "gone.retake")])] == ["Course"]


def test_removing_a_recording_closes_its_gap_and_keeps_the_rest(tmp_path):
    import soundfile as sf
    import numpy as np

    from retake.edit.edl import Clip, Edit
    from retake.project import Project
    from retake.session.takes import COMPLETE, Marker

    project = Project.create(tmp_path / "P", "P")
    source = tmp_path / "ep.md"
    source.write_text("One two.")
    item = project.add_script(source)
    for index, seconds in ((1, 10.0), (2, 5.0), (3, 8.0)):
        audio = item.folder / f"part-{index:03d}.flac"
        sf.write(audio, np.zeros(int(16000 * seconds), dtype=np.float32), 16000)
        (item.folder / f"part-{index:03d}.mkv").write_bytes(b"video")
        item.add_part(index, audio, seconds)
    log = item.load_takes()
    for start in (2.0, 12.0, 17.0):
        take = log.new_take(None, start, "t")
        take.end, take.status = start + 1.0, COMPLETE
    log.markers.append(Marker(1, "pause", 13.0, 13.5, "pause"))
    log.markers.append(Marker(2, "mark", 18.0, 18.0, "mark"))
    log.save()
    item.save_edit(Edit(clips=[Clip(1, 2.0, 3.0), Clip(2, 12.0, 13.0), Clip(3, 17.0, 18.0)], source_duration=23.0))

    files = item.remove_part(2)

    assert sorted(f.name for f in files) == ["part-002.flac", "part-002.mkv"]
    assert [p.index for p in item.parts] == [1, 3] and item.parts[1].start == 10.0
    assert [(t.start, t.end) for t in item.load_takes().takes] == [(2.0, 3.0), (12.0, 13.0)]
    assert [(m.kind, m.start) for m in item.load_takes().markers] == [("mark", 13.0)]
    edit = item.load_edit()
    assert [(c.start, c.end) for c in edit.clips] == [(2.0, 3.0), (12.0, 13.0)] and edit.source_duration == 18.0
