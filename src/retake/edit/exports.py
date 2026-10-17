from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from ..script.lexicon import atomic_write
from ..session import takes as kinds
from ..session.takes import TakeLog
from .edl import Edit

MAX_LINE = 42
MAX_CUE = 6.0


def _stamp(seconds: float, separator: str = ".") -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}".replace(".", separator)


def edited_words(log: TakeLog, edit: Edit) -> list[tuple[float, float, str]]:
    kept_takes = {c.take for c in edit.clips if c.take is not None}
    words = []
    for take in log.takes:
        if take.id not in kept_takes:
            continue
        for word in take.words:
            start = edit.to_output(word.start)
            end = edit.to_output(word.end)
            if start is None or end is None:
                continue
            words.append((start, end, word.text))
    words.sort()
    return words


def cues(words: list[tuple[float, float, str]]) -> list[tuple[float, float, list[tuple[float, float, str]]]]:
    result = []
    current: list[tuple[float, float, str]] = []
    for word in words:
        text = " ".join(w[2] for w in current + [word])
        too_long = len(text) > MAX_LINE * 2 or (current and word[1] - current[0][0] > MAX_CUE)
        if current and (too_long or word[0] - current[-1][1] > 1.0):
            result.append((current[0][0], current[-1][1], current))
            current = []
        current.append(word)
        if word[2].endswith((".", "?", "!")) and len(" ".join(w[2] for w in current)) > 20:
            result.append((current[0][0], current[-1][1], current))
            current = []
    if current:
        result.append((current[0][0], current[-1][1], current))
    return result


def _wrap(text: str) -> str:
    if len(text) <= MAX_LINE:
        return text
    words = text.split()
    best = len(words) // 2
    return " ".join(words[:best]) + "\n" + " ".join(words[best:])


def webvtt(words: list[tuple[float, float, str]], karaoke: bool = False) -> str:
    lines = ["WEBVTT", ""]
    for index, (start, end, group) in enumerate(cues(words), 1):
        lines.append(str(index))
        lines.append(f"{_stamp(start)} --> {_stamp(end)}")
        if karaoke:
            body = " ".join(f"<{_stamp(w[0])}>{w[2]}" for w in group)
        else:
            body = _wrap(" ".join(w[2] for w in group))
        lines.append(body)
        lines.append("")
    return "\n".join(lines)


def srt(words: list[tuple[float, float, str]]) -> str:
    lines = []
    for index, (start, end, group) in enumerate(cues(words), 1):
        lines.append(str(index))
        lines.append(f"{_stamp(start, ',')} --> {_stamp(end, ',')}")
        lines.append(_wrap(" ".join(w[2] for w in group)))
        lines.append("")
    return "\n".join(lines)


def audacity_labels(log: TakeLog) -> str:
    rows = []
    for take in log.takes:
        label = f"take {take.id} s{take.sentence if take.sentence is not None else '-'} {take.status}"
        if take.reason:
            label += f" ({take.reason})"
        rows.append((take.start, take.end or take.start, label))
    for marker in log.markers:
        rows.append((marker.start, marker.end, f"{marker.kind}: {marker.label}".strip()))
    rows.sort()
    return "".join(f"{a:.6f}\t{b:.6f}\t{text}\n" for a, b, text in rows)


def chapters(log: TakeLog, edit: Edit | None) -> list[tuple[float, str]]:
    result = []
    for marker in log.markers_of(kinds.CHAPTER, kinds.MARK):
        when = marker.start
        if edit is not None:
            clip = edit.clip_at(when)
            if clip is not None and when - clip.start <= 0.25:
                when = clip.start
        time = edit.to_output(when) if edit else when
        if time is None and edit is not None:
            following = [c for c in edit.timeline() if c.start >= marker.start]
            time = edit.to_output(following[0].start) if following else None
        if time is not None:
            result.append((time, marker.label))
    result.sort()
    deduped = []
    for time, label in result:
        if deduped and abs(deduped[-1][0] - time) < 0.5:
            continue
        deduped.append((time, label))
    return deduped


def ffmetadata(chapter_list: list[tuple[float, str]], total: float, title: str = "") -> str:
    lines = [";FFMETADATA1"]
    if title:
        lines.append(f"title={_escape(title)}")
    for index, (start, label) in enumerate(chapter_list):
        end = chapter_list[index + 1][0] if index + 1 < len(chapter_list) else total
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(start * 1000)}", f"END={int(max(end, start + 0.001) * 1000)}", f"title={_escape(label)}"]
    return "\n".join(lines) + "\n"


def _escape(text: str) -> str:
    for ch in "\\=;#\n":
        text = text.replace(ch, "\\" + ch)
    return text


def _time(value: float, rate: float) -> dict:
    return {"OTIO_SCHEMA": "RationalTime.1", "rate": rate, "value": round(value * rate, 3)}


def _range(start: float, duration: float, rate: float) -> dict:
    return {"OTIO_SCHEMA": "TimeRange.1", "start_time": _time(start, rate), "duration": _time(duration, rate)}


def _reference(path: Path, duration: float, rate: float) -> dict:
    return {
        "OTIO_SCHEMA": "ExternalReference.1",
        "metadata": {},
        "name": path.name,
        "available_range": _range(0, duration, rate),
        "target_url": "file://" + quote(str(path.resolve())),
    }


def _marker(name: str, start: float, rate: float, color: str = "RED", comment: str = "") -> dict:
    return {
        "OTIO_SCHEMA": "Marker.2",
        "metadata": {},
        "name": name,
        "color": color,
        "comment": comment,
        "marked_range": _range(start, 0, rate),
    }


def otio(
    log: TakeLog,
    edit: Edit | None,
    sources: list,
    video_durations: dict | None = None,
    rate: float = 30.0,
    name: str = "retake",
) -> str:
    """sources are render.Source entries: each recording's audio, video and place on the timeline."""
    video_durations = video_durations or {}
    with_video = any(source.video is not None for source in sources)
    if edit is not None:
        spans = [(c.start, c.end, c.label or f"clip {c.id}") for c in edit.timeline()]
    else:
        spans = [(source.start, source.end, source.audio.stem) for source in sources]
    audio_clips, video_clips = [], []
    for start, end, label in spans:
        for source in sources:
            piece_start, piece_end = max(start, source.start), min(end, source.end)
            if piece_end - piece_start <= 1e-6:
                continue
            local = piece_start - source.start
            length = piece_end - piece_start
            audio_clips.append({
                "OTIO_SCHEMA": "Clip.1", "metadata": {}, "name": label, "source_range": _range(local, length, rate),
                "effects": [], "markers": [], "media_reference": _reference(source.audio, source.duration, rate),
            })
            if not with_video:
                continue
            if source.video is None:
                video_clips.append({"OTIO_SCHEMA": "Gap.1", "metadata": {}, "name": "", "source_range": _range(0.0, length, rate), "effects": [], "markers": []})
                continue
            video_clips.append({
                "OTIO_SCHEMA": "Clip.1", "metadata": {}, "name": label,
                "source_range": _range(max(0.0, local - source.offset_at(local)), length, rate), "effects": [], "markers": [],
                "media_reference": _reference(source.video, video_durations.get(source.video) or source.duration, rate),
            })
    markers = []
    colors = {kinds.CHAPTER: "BLUE", kinds.MARK: "BLUE", kinds.OFF_SCRIPT: "YELLOW", kinds.FLAG: "RED", kinds.CAMERA: "PURPLE", kinds.SCENE: "PURPLE"}
    for marker in log.markers:
        if marker.kind not in colors:
            continue
        time = edit.to_output(marker.start) if edit else marker.start
        if time is not None:
            markers.append(_marker(f"{marker.kind}: {marker.label}", time, rate, colors[marker.kind]))
    for take in log.takes:
        for flagged in take.flagged:
            when = flagged.get("start") or take.start
            time = edit.to_output(when) if edit else when
            if time is not None:
                markers.append(_marker(f"pronunciation: {flagged.get('text', '')}", time, rate, "RED", flagged.get("heard", "")))
    tracks = []
    if video_clips:
        tracks.append({"OTIO_SCHEMA": "Track.1", "metadata": {}, "name": "Video", "kind": "Video", "children": video_clips, "effects": [], "markers": [], "source_range": None})
    tracks.append({"OTIO_SCHEMA": "Track.1", "metadata": {}, "name": "Voice", "kind": "Audio", "children": audio_clips, "effects": [], "markers": [], "source_range": None})
    timeline = {
        "OTIO_SCHEMA": "Timeline.1",
        "metadata": {"retake": {"version": 1}},
        "name": name,
        "global_start_time": None,
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "metadata": {},
            "name": "tracks",
            "children": tracks,
            "effects": [],
            "markers": markers,
            "source_range": None,
        },
    }
    return json.dumps(timeline, indent=2, ensure_ascii=False)


def script_timing(script, log: TakeLog, edit: Edit | None, name: str = "") -> dict:
    complete = [t for t in log.takes if t.status == "complete" and t.sentence is not None]
    clips_by_take: dict[int, list] = {}
    if edit is not None:
        for clip in edit.timeline():
            if clip.take is not None:
                clips_by_take.setdefault(clip.take, []).append(clip)
    sentences = []
    for sentence in script.sentences:
        if not sentence.words and sentence.kind != "adlib":
            continue
        candidates = [t for t in complete if t.sentence == sentence.index]
        if edit is not None:
            chosen = next((t for t in candidates if t.id in clips_by_take), None)
        else:
            chosen = candidates[-1] if candidates else None
        section = script.sections[sentence.section] if sentence.section >= 0 else None
        entry = {
            "index": sentence.index,
            "kind": sentence.kind,
            "text": sentence.display_text or sentence.note,
            "section": sentence.section,
            "section_title": section.title if section else "",
            "section_id": section.meta.get("id") if section else None,
            "beat": sentence.meta.get("beat"),
            "meta": {k: v for k, v in sentence.meta.items() if k not in ("beat", "section_id")},
            "takes": [t.id for t in log.takes if t.sentence == sentence.index],
            "take": chosen.id if chosen else None,
            "score": chosen.score if chosen else None,
            "source": None,
            "output": None,
            "words": [],
        }
        if chosen is not None:
            entry["source"] = {"start": round(chosen.start, 3), "end": round(chosen.end or chosen.start, 3)}
            clips = clips_by_take.get(chosen.id, [])
            if clips and edit is not None:
                start = edit.to_output(clips[0].start)
                end = edit.to_output(clips[-1].end)
                if start is not None and end is not None:
                    entry["output"] = {"start": round(start, 3), "end": round(end, 3)}
            for word in chosen.words:
                row = {"text": word.text, "source_start": round(word.start, 3), "source_end": round(word.end, 3)}
                if edit is not None:
                    out_start, out_end = edit.to_output(word.start), edit.to_output(word.end)
                    row["output_start"] = None if out_start is None else round(out_start, 3)
                    row["output_end"] = None if out_end is None else round(out_end, 3)
                if word.score is not None:
                    row["score"] = word.score
                entry["words"].append(row)
        sentences.append(entry)
    timeline = "output" if edit is not None else "source"
    beats: list[dict] = []
    for entry in sentences:
        span = entry[timeline]
        key = (entry["section"], entry["beat"])
        if beats and (beats[-1]["section"], beats[-1]["beat"]) == key:
            beat = beats[-1]
            beat["sentences"].append(entry["index"])
        else:
            beat = {"section": entry["section"], "section_id": entry["section_id"], "beat": entry["beat"], "sentences": [entry["index"]], "start": None, "end": None}
            beats.append(beat)
        if span:
            beat["start"] = span["start"] if beat["start"] is None else min(beat["start"], span["start"])
            beat["end"] = span["end"] if beat["end"] is None else max(beat["end"], span["end"])
    sections = []
    for section in script.sections:
        spans = [e[timeline] for e in sentences if e["section"] == section.index and e[timeline]]
        sections.append({
            "index": section.index,
            "title": section.title,
            "level": section.level,
            "id": section.meta.get("id"),
            "meta": {k: v for k, v in section.meta.items() if k != "id"},
            "start": min((s["start"] for s in spans), default=None),
            "end": max((s["end"] for s in spans), default=None),
        })
    return {
        "version": 1,
        "title": script.title,
        "session": name,
        "timeline": timeline,
        "sections": sections,
        "beats": beats,
        "sentences": sentences,
    }


def write(path: Path, text: str) -> Path:
    atomic_write(path, text)
    return path
