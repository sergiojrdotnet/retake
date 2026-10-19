from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from ..script.lexicon import atomic_write
from ..session import takes as kinds
from ..session.takes import TakeLog
from .edl import Edit

MAX_CUE = 6.0


def _stamp(seconds: float, separator: str = ".") -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}".replace(".", separator)


def edited_words(log: TakeLog, edit: Edit, aligned: dict[int, list[dict]] | None = None) -> list[tuple[float, float, str]]:
    """The cut's words in output time: aligned ones where given (every script word), else the recognizer's."""
    aligned = aligned or {}
    kept_takes = {c.take for c in edit.clips if c.take is not None}
    words = [(row["output_start"], row["output_end"], row["text"]) for rows in aligned.values() for row in rows]
    for take in log.takes:
        if take.id not in kept_takes or take.sentence in aligned:
            continue
        for word in take.words:
            start = edit.to_output(word.start)
            end = edit.to_output(word.end)
            if start is None or end is None:
                continue
            words.append((start, end, word.text))
    words.sort()
    return words


def cues(words: list[tuple[float, float, str]], line: int = 42, lines: int = 2) -> list[tuple[float, float, list[tuple[float, float, str]]]]:
    result = []
    current: list[tuple[float, float, str]] = []
    for word in words:
        text = " ".join(w[2] for w in current + [word])
        too_long = len(text) > line * lines or (current and word[1] - current[0][0] > MAX_CUE)
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


def _wrap(text: str, line: int = 42) -> list[str]:
    if len(text) <= line:
        return [text]
    words = text.split()
    split = min(range(1, len(words)), key=lambda i: max(len(" ".join(words[:i])), len(" ".join(words[i:]))), default=1)
    return [" ".join(words[:split]), " ".join(words[split:])]


def webvtt(words: list[tuple[float, float, str]], karaoke: bool = False, line: int = 42, lines: int = 2) -> str:
    rows = ["WEBVTT", ""]
    for index, (start, end, group) in enumerate(cues(words, line, lines), 1):
        rows.append(str(index))
        rows.append(f"{_stamp(start)} --> {_stamp(end)}")
        if karaoke:
            rows.append(" ".join(f"<{_stamp(w[0])}>{w[2]}" for w in group))
        else:
            rows += _wrap(" ".join(w[2] for w in group), line)
        rows.append("")
    return "\n".join(rows)


def srt(words: list[tuple[float, float, str]], line: int = 42, lines: int = 2) -> str:
    rows = []
    for index, (start, end, group) in enumerate(cues(words, line, lines), 1):
        rows.append(str(index))
        rows.append(f"{_stamp(start, ',')} --> {_stamp(end, ',')}")
        rows += _wrap(" ".join(w[2] for w in group), line)
        rows.append("")
    return "\n".join(rows)


def _ass_time(seconds: float) -> str:
    hundredths = round(max(0.0, seconds) * 100)
    hours, rest = divmod(hundredths, 360000)
    minutes, rest = divmod(rest, 6000)
    secs, fraction = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{fraction:02d}"


def ass(words: list[tuple[float, float, str]], width: int, height: int, line: int = 42, lines: int = 2) -> str:
    """Captions styled for burning into a picture of this size: sized on its short side, so portrait
    and landscape get the same lettering."""
    portrait = height > width
    size = round(min(width, height) * 0.05)
    side = round(width * 0.05)
    # Shorts and Reels cover the bottom fifth of a portrait video with their own buttons.
    bottom = round(height * (0.22 if portrait else 0.07))
    rows = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,Sans,{size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{max(2, round(size / 14))},0,2,{side},{side},{bottom},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for start, end, group in cues(words, line, lines):
        text = " ".join(w[2] for w in group).replace("{", "(").replace("}", ")").replace("\\", "/")
        rows.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,," + r"\N".join(_wrap(text, line)))
    return "\n".join(rows) + "\n"


def transcript(words: list[tuple[float, float, str]]) -> str:
    """The edited narration as plain text: a line per sentence, a blank line where you paused."""
    rows: list[str] = []
    current: list[str] = []
    previous_end = None
    for start, end, text in words:
        if previous_end is not None and start - previous_end > 2.0:
            if current:
                rows.append(" ".join(current))
                current = []
            if rows and rows[-1]:
                rows.append("")
        current.append(text)
        if text.endswith((".", "?", "!")):
            rows.append(" ".join(current))
            current = []
        previous_end = end
    if current:
        rows.append(" ".join(current))
    return "\n".join(rows) + "\n"


CAPTION_FORMATS = {
    "srt": "captions.srt",
    "vtt": "captions.vtt",
    "vtt-words": "captions-words.vtt",
    "txt": "transcript.txt",
}


def captions_file(words: list[tuple[float, float, str]], settings: dict) -> tuple[str, str]:
    """The file name and text for the Captions export with its remembered choices (config [export])."""
    fmt = settings["captions_format"]
    line, lines = int(settings["caption_line"]), int(settings["caption_lines"])
    if fmt == "vtt":
        text = webvtt(words, line=line, lines=lines)
    elif fmt == "vtt-words":
        text = webvtt(words, karaoke=True, line=line, lines=lines)
    elif fmt == "txt":
        text = transcript(words)
    else:
        text = srt(words, line, lines)
    return CAPTION_FORMATS[fmt], text


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


def section_starts(script, edit: Edit) -> list[tuple[float, str]]:
    """Where each of the script's sections starts on the edit's timeline: at its first kept
    sentence, whichever recording that came from."""
    starts = []
    seen: set[int] = set()
    position = 0.0
    for clip in edit.timeline():
        if clip.sentence is not None and clip.sentence < len(script.sentences):
            section = script.sentences[clip.sentence].section
            if section >= 0 and section not in seen:
                seen.add(section)
                starts.append((position, script.sections[section].title))
        position += clip.duration
    return starts


def chapters(log: TakeLog, edit: Edit | None, script=None) -> list[tuple[float, str]]:
    """Chapter starts on the edit's timeline: the script's sections, plus the marks you dropped while
    recording. The chapter markers logged while reading aren't used: every recording logs its own,
    at its first take of a section, whether or not that take made the edit. Without the script
    (unreadable), the logged markers are all there is."""
    scripted = script is not None and edit is not None
    result = section_starts(script, edit) if scripted else []
    for marker in log.markers_of(*((kinds.MARK,) if scripted else (kinds.CHAPTER, kinds.MARK))):
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


def _spans(edit: Edit | None, sources: list):
    """The pieces a timeline places, in order: (label, source, time in the source's audio, length,
    where it lands on the timeline)."""
    if edit is not None:
        spans = [(c.start, c.end, c.label or f"clip {c.id}") for c in edit.timeline()]
    else:
        spans = [(source.start, source.end, source.audio.stem) for source in sources]
    position = 0.0
    for start, end, label in spans:
        for source in sources:
            piece_start, piece_end = max(start, source.start), min(end, source.end)
            if piece_end - piece_start <= 1e-6:
                continue
            yield label, source, piece_start - source.start, piece_end - piece_start, position
            position += piece_end - piece_start


def _video_time(source, local: float) -> float:
    return max(0.0, local - source.offset_at(local))


def _timeline_markers(log: TakeLog, edit: Edit | None, script=None) -> list[tuple[float, str, str, str]]:
    """(time, name, color, comment) for the markers worth seeing in an editor."""
    colors = {kinds.CHAPTER: "BLUE", kinds.MARK: "BLUE", kinds.OFF_SCRIPT: "YELLOW", kinds.FLAG: "RED"}
    scripted = script is not None and edit is not None
    markers = [(time, f"{kinds.CHAPTER}: {title}", "BLUE", "") for time, title in section_starts(script, edit)] if scripted else []
    for marker in log.markers:
        if marker.kind not in colors or (scripted and marker.kind == kinds.CHAPTER):
            continue
        time = edit.to_output(marker.start) if edit else marker.start
        if time is not None:
            markers.append((time, f"{marker.kind}: {marker.label}", colors[marker.kind], ""))
    for take in log.takes:
        for flagged in take.flagged:
            when = flagged.get("start") or take.start
            time = edit.to_output(when) if edit else when
            if time is not None:
                markers.append((time, f"pronunciation: {flagged.get('text', '')}", "RED", flagged.get("heard", "")))
    return sorted(markers)


def otio(log: TakeLog, edit: Edit | None, sources: list, probes: dict | None = None, rate: float = 30.0, name: str = "retake", script=None) -> str:
    """sources are render.Source entries: each recording's audio, video and place on the timeline;
    probes maps media paths to their media.MediaInfo."""
    probes = probes or {}
    with_video = any(source.video is not None for source in sources)
    audio_clips, video_clips = [], []
    for label, source, local, length, _ in _spans(edit, sources):
        audio_clips.append({
            "OTIO_SCHEMA": "Clip.1", "metadata": {}, "name": label, "source_range": _range(local, length, rate),
            "effects": [], "markers": [], "media_reference": _reference(source.audio, source.duration, rate),
        })
        if not with_video:
            continue
        if source.video is None:
            video_clips.append({"OTIO_SCHEMA": "Gap.1", "metadata": {}, "name": "", "source_range": _range(0.0, length, rate), "effects": [], "markers": []})
            continue
        probe = probes.get(source.video)
        video_clips.append({
            "OTIO_SCHEMA": "Clip.1", "metadata": {}, "name": label,
            "source_range": _range(_video_time(source, local), length, rate), "effects": [], "markers": [],
            "media_reference": _reference(source.video, (probe.duration if probe else 0.0) or source.duration, rate),
        })
    markers = [_marker(marker_name, time, rate, color, comment) for time, marker_name, color, comment in _timeline_markers(log, edit, script)]
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


def _timecode(frames: int, fps: int) -> str:
    hours, rest = divmod(frames, fps * 3600)
    minutes, rest = divmod(rest, fps * 60)
    seconds, frame = divmod(rest, fps)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frame:02d}"


def edl(log: TakeLog, edit: Edit | None, sources: list, rate: float = 30.0, name: str = "retake") -> str:
    """A CMX 3600 edit list. Every event names its file in a FROM CLIP NAME comment, which is how
    Resolve and Premiere link it to the media; the audio and video recordings are separate files, so
    each piece is a video event and an audio event."""
    fps = max(1, round(rate))
    rows = [f"TITLE: {name}", "FCM: NON-DROP FRAME", ""]
    event = 0
    for _, source, local, length, position in _spans(edit, sources):
        record_in, record_out = round(position * fps), round((position + length) * fps)
        if record_out <= record_in:
            continue
        tracks = [("V", source.video, _video_time(source, local))] if source.video is not None else []
        tracks.append(("A", source.audio, local))
        for track, path, start in tracks:
            event += 1
            source_in = round(start * fps)
            source_out = source_in + record_out - record_in
            rows.append(f"{event:03d}  AX       {track:<5} C        {_timecode(source_in, fps)} {_timecode(source_out, fps)} "
                        f"{_timecode(record_in, fps)} {_timecode(record_out, fps)}")
            rows.append(f"* FROM CLIP NAME: {path.name}")
            rows.append("")
    return "\n".join(rows)


def fcp_xml(log: TakeLog, edit: Edit | None, sources: list, probes: dict | None = None, rate: float = 30.0, name: str = "retake", script=None) -> str:
    """A Final Cut Pro 7 XML (xmeml) sequence, which Premiere, Resolve, Kdenlive and Shotcut import."""
    from xml.etree import ElementTree as ET

    probes = probes or {}
    fps = max(1, round(rate))

    def add(parent, tag: str, text=None, **attributes):
        element = ET.SubElement(parent, tag, **attributes)
        if text is not None:
            element.text = str(text)
        return element

    def add_rate(parent) -> None:
        element = add(parent, "rate")
        add(element, "timebase", fps)
        add(element, "ntsc", "FALSE")

    files: dict[Path, str] = {}

    def add_file(parent, path: Path, kind: str) -> None:
        if path in files:
            add(parent, "file", id=files[path])
            return
        files[path] = f"file-{len(files) + 1}"
        probe = probes.get(path)
        element = add(parent, "file", id=files[path])
        add(element, "name", path.name)
        add(element, "pathurl", "file://localhost" + quote(str(path.resolve())))
        add_rate(element)
        add(element, "duration", round((probe.duration if probe else 0.0) * fps))
        described = add(element, "media")
        if kind == "video":
            characteristics = add(add(described, "video"), "samplecharacteristics")
            add(characteristics, "width", probe.width if probe else 1920)
            add(characteristics, "height", probe.height if probe else 1080)
        else:
            add(add(described, "audio"), "channelcount", (probe.channels if probe else 0) or 1)

    root = ET.Element("xmeml", version="5")
    sequence = add(root, "sequence", id="sequence-1")
    add(sequence, "name", name)
    duration = add(sequence, "duration")
    add_rate(sequence)
    described = add(sequence, "media")
    first_video = next((probes.get(s.video) for s in sources if s.video is not None), None)
    video_track = None
    if any(source.video is not None for source in sources):
        video = add(described, "video")
        characteristics = add(add(video, "format"), "samplecharacteristics")
        add_rate(characteristics)
        add(characteristics, "width", first_video.width if first_video else 1920)
        add(characteristics, "height", first_video.height if first_video else 1080)
        video_track = add(video, "track")
    audio_track = add(add(described, "audio"), "track")
    count = 0
    end = 0
    for label, source, local, length, position in _spans(edit, sources):
        record_in, record_out = round(position * fps), round((position + length) * fps)
        if record_out <= record_in:
            continue
        end = record_out
        pieces = [(audio_track, source.audio, local, "audio")]
        if video_track is not None and source.video is not None:
            pieces.insert(0, (video_track, source.video, _video_time(source, local), "video"))
        for track, path, start, kind in pieces:
            count += 1
            clip = add(track, "clipitem", id=f"clipitem-{count}")
            add(clip, "name", label)
            probe = probes.get(path)
            add(clip, "duration", round((probe.duration if probe else source.duration) * fps))
            add_rate(clip)
            add(clip, "start", record_in)
            add(clip, "end", record_out)
            add(clip, "in", round(start * fps))
            add(clip, "out", round(start * fps) + record_out - record_in)
            add_file(clip, path, kind)
            if kind == "audio":
                track_source = add(clip, "sourcetrack")
                add(track_source, "mediatype", "audio")
                add(track_source, "trackindex", 1)
    duration.text = str(end)
    for time, marker_name, _, comment in _timeline_markers(log, edit, script):
        marker = add(sequence, "marker")
        add(marker, "name", marker_name)
        add(marker, "comment", comment)
        add(marker, "in", round(time * fps))
        add(marker, "out", -1)
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="unicode") + "\n"


TIMELINE_FORMATS = {"otio": "timeline.otio", "edl": "timeline.edl", "fcpxml": "timeline.xml"}


def timeline_file(log: TakeLog, edit: Edit | None, sources: list, probes: dict, settings: dict, name: str, script=None) -> tuple[str, str]:
    """The file name and text for the Timeline export, at the video's frame rate (30 without video)."""
    fmt = settings["timeline_format"]
    first_video = next((probes.get(s.video) for s in sources if s.video is not None and probes.get(s.video)), None)
    rate = float(round(first_video.fps)) if first_video and first_video.fps else 30.0
    if fmt == "edl":
        text = edl(log, edit, sources, rate, name)
    elif fmt == "fcpxml":
        text = fcp_xml(log, edit, sources, probes, rate, name, script)
    else:
        text = otio(log, edit, sources, probes, rate, name, script)
    return TIMELINE_FORMATS[fmt], text


def script_timing(script, log: TakeLog, edit: Edit | None, name: str = "", aligned: dict[int, list[dict]] | None = None) -> dict:
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
            if aligned and sentence.index in aligned and edit is not None:
                scores = {word.word: word.score for word in chosen.words if word.score is not None}
                for row in aligned[sentence.index]:
                    entry["words"].append({
                        "text": row["text"], "source_start": round(row["source_start"], 3), "source_end": round(row["source_end"], 3),
                        "output_start": round(row["output_start"], 3), "output_end": round(row["output_end"], 3),
                        **({"score": scores[row["word"]]} if row["word"] in scores else {}),
                    })
                sentences.append(entry)
                continue
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
