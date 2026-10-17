from __future__ import annotations

from dataclasses import dataclass

from ..session import takes as kinds
from ..session.takes import COMPLETE, Take, TakeLog
from .edl import Edit


@dataclass
class Rules:
    keep: str = "last"
    handle_before: float = 0.08
    handle_after: float = 0.15
    max_pause: float = 0.7
    extra_speech: str = "between"
    crossfade_ms: int = 15
    camera_crossfade_ms: int = 0
    order: str = "source"

    @classmethod
    def from_config(cls, edit: dict, strictness: dict) -> Rules:
        return cls(
            keep=edit.get("keep", "last"),
            handle_before=float(edit.get("handle_before", 0.08)),
            handle_after=float(edit.get("handle_after", 0.15)),
            max_pause=float(edit.get("max_pause", 0.7)),
            extra_speech=strictness.get("extra_speech", "between"),
            crossfade_ms=int(edit.get("crossfade_ms", 15)),
            camera_crossfade_ms=int(edit.get("camera_crossfade_ms", 0)),
            order=edit.get("order", "source"),
        )


def _choose(takes: list[Take], keep: str) -> Take:
    if keep == "best":
        scored = [t for t in takes if t.score is not None]
        if scored:
            return max(scored, key=lambda t: (t.score, t.id))
    preferred = [t for t in takes if t.preferred]
    if preferred:
        return preferred[-1]
    return takes[-1]


def _subtract(ranges: list[tuple[float, float]], holes: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result = []
    for start, end in ranges:
        pieces = [(start, end)]
        for a, b in holes:
            next_pieces = []
            for s, e in pieces:
                if b <= s or a >= e:
                    next_pieces.append((s, e))
                    continue
                if a > s:
                    next_pieces.append((s, a))
                if b < e:
                    next_pieces.append((b, e))
            pieces = next_pieces
        result.extend(pieces)
    return result


def _removable(log: TakeLog, rules: Rules) -> list[tuple[float, float]]:
    removable = [(m.start, m.end) for m in log.markers_of(kinds.COMMAND, kinds.TTS, kinds.PAUSE, kinds.DRILL) if m.end > m.start]
    if rules.extra_speech == "strict":
        removable += [(m.start, m.end) for m in log.markers_of(kinds.OFF_SCRIPT, kinds.FILLER) if m.data.get("inside")]
    return removable


def _take_clips(edit: Edit, take: Take, rules: Rules, duration: float, removable: list, adlibs: list, limits: tuple[float, float]) -> None:
    start = max(limits[0], take.start - rules.handle_before)
    end = min(limits[1], duration, (take.end or take.start) + rules.handle_after)
    is_adlib = any(a <= take.start + 0.01 and take.end <= b + 0.01 for a, b in adlibs)
    for piece_start, piece_end in _subtract([(start, end)], removable):
        edit.clips.append(edit_clip(edit, piece_start, piece_end, take, "adlib" if is_adlib else "take"))


def _limits(take: Take, boundaries: list[float], duration: float) -> tuple[float, float]:
    """The part a take was recorded in: handles never reach into the neighbouring part."""
    low = max((b for b in boundaries if b <= take.start), default=0.0)
    high = min((b for b in boundaries if b > take.start), default=duration)
    return low, high


def _good_takes(log: TakeLog) -> dict[int | None, list[Take]]:
    grouped: dict[int | None, list[Take]] = {}
    for take in log.takes:
        if take.status == COMPLETE and take.end is not None:
            grouped.setdefault(take.sentence, []).append(take)
    for sentence, takes in grouped.items():
        fresh = [t for t in takes if not t.stale]
        if fresh and sentence is not None:
            grouped[sentence] = fresh
    return grouped


def auto_edit(log: TakeLog, duration: float, rules: Rules, boundaries: list[float] | None = None) -> Edit:
    boundaries = sorted(boundaries or [])
    edit = Edit(source_duration=duration, order=rules.order, crossfade_ms=rules.crossfade_ms, camera_crossfade_ms=rules.camera_crossfade_ms, rules=rules.__dict__.copy())
    grouped = _good_takes(log)
    chosen: list[Take] = list(grouped.pop(None, []))
    for sentence_takes in grouped.values():
        chosen.append(_choose(sentence_takes, rules.keep))
    chosen.sort(key=lambda t: t.start)
    removable = _removable(log, rules)
    adlibs = [(m.start, m.end) for m in log.markers_of(kinds.ADLIB)]
    if rules.extra_speech == "keep":
        kept_extra = [(m.start, m.end) for m in log.markers_of(kinds.OFF_SCRIPT) if not m.data.get("inside")]
    else:
        kept_extra = []
    for take in chosen:
        _take_clips(edit, take, rules, duration, removable, adlibs, _limits(take, boundaries, duration))
    for start, end in kept_extra:
        for piece_start, piece_end in _subtract([(start - rules.handle_before, end + rules.handle_after)], removable):
            edit.clips.append(edit_clip(edit, piece_start, piece_end, None, "extra"))
    edit.clips.sort(key=lambda c: (c.start, c.id))
    _close_small_gaps(edit, rules.max_pause, removable, boundaries)
    edit.normalize()
    return edit


def update_sentences(edit: Edit, log: TakeLog, sentences: set[int], rules: Rules, duration: float, boundaries: list[float] | None = None) -> list[int]:
    """Swaps in the chosen take for each of these sentences and leaves the rest of the edit alone,
    so a pickup or a later recording doesn't undo hand edits elsewhere."""
    boundaries = sorted(boundaries or [])
    grouped = _good_takes(log)
    removable = _removable(log, rules)
    adlibs = [(m.start, m.end) for m in log.markers_of(kinds.ADLIB)]
    edit.source_duration = duration
    updated = []
    for sentence in sorted(sentences):
        takes = grouped.get(sentence)
        if not takes:
            continue
        take = _choose(takes, rules.keep)
        edit.clips = [c for c in edit.clips if c.sentence != sentence]
        _take_clips(edit, take, rules, duration, removable, adlibs, _limits(take, boundaries, duration))
        updated.append(sentence)
    edit.clips.sort(key=lambda c: (c.start, c.id))
    edit.normalize()
    return updated


def edit_clip(edit: Edit, start: float, end: float, take: Take | None, kind: str):
    from .edl import Clip

    clip = Clip(edit.next_id, start, end, take.id if take else None, take.sentence if take else None, kind, (take.text[:60] if take else ""))
    edit.next_id += 1
    return clip


def _close_small_gaps(edit: Edit, max_pause: float, removable: list[tuple[float, float]], boundaries: list[float] | None = None) -> None:
    clips = edit.clips
    for left, right in zip(clips, clips[1:]):
        gap = right.start - left.end
        crosses = any(left.end < b <= right.start for b in boundaries or [])
        if 0 < gap <= max_pause and not crosses and not any(a < right.start and b > left.end for a, b in removable):
            left.end = right.start


def flag_screen_changes(edit: Edit, changes: list[float]) -> list[tuple[float, float]]:
    flagged = []
    clips = sorted(edit.clips, key=lambda c: c.start)
    for left, right in zip(clips, clips[1:]):
        if any(left.end < t < right.start for t in changes):
            flagged.append((left.end, right.start))
    return flagged
