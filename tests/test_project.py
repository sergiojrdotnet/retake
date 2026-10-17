import json

import numpy as np
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
    item_log = TakeLog(tmp_path / "takes.json")
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
    assert json.loads((tmp_path / "takes.json").read_text())["takes"][1]["start"] == 10.5


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
    item = project.add_free()
    tone(item.folder / "part-001.flac", 2.0)
    pending = TakeLog(item.folder / "part-001.takes.json")
    pending.new_take(None, 0.5, "hello")
    assert projects.recover_parts(item) == [1]
    assert item.parts[0].kind == "recovered" and item.load_takes().takes[0].start == 0.5
    assert not (item.folder / "part-001.takes.json").exists()


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
