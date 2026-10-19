from __future__ import annotations

from dataclasses import asdict, dataclass

from ..session import takes as kinds
from ..session.takes import COMPLETE, REJECTED, Take, TakeLog
from ..session.tracker import PREROLL
from .edl import Clip, Edit
from .quiet import Quiet


BLOCK_CONTEXT = 1.0
# Whisper's word times can be several tenths off (a word may swallow the pause after it, or start in the
# pause before it), so each edge goes in the pause the audio shows near them.
PAUSE = 0.12
SENTENCE_PAUSE = 0.25
REACH = 0.5
TAIL_REACH = 1.0
# How far before the first word heard a sentence may begin when the recognizer dropped its opening words,
# and how long a reader may pause after a label like "Performance:".
OPENER_REACH = 1.2
LABEL_PAUSE = 1.5


@dataclass
class Rules:
    keep: str = "last"
    handle_before: float = 0.08
    handle_after: float = 0.15
    max_pause: float = 0.7
    sentence_pause: float = 0.5
    extra_speech: str = "between"
    crossfade_ms: int = 15
    camera_crossfade_ms: int = 0

    @classmethod
    def from_config(cls, edit: dict, strictness: dict) -> Rules:
        return cls(
            keep=edit.get("keep", "last"),
            handle_before=float(edit.get("handle_before", 0.08)),
            handle_after=float(edit.get("handle_after", 0.15)),
            max_pause=float(edit.get("max_pause", 0.7)),
            sentence_pause=float(edit.get("sentence_pause", 0.5)),
            extra_speech=strictness.get("extra_speech", "between"),
            crossfade_ms=int(edit.get("crossfade_ms", 15)),
            camera_crossfade_ms=int(edit.get("camera_crossfade_ms", 0)),
        )


def _choose(takes: list[Take], keep: str) -> Take:
    if keep == "best":
        scored = [t for t in takes if t.score is not None]
        if scored:
            return max(scored, key=lambda t: (t.score, t.id))
    return max(takes, key=lambda t: t.id)


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


def _bare(text: str) -> str:
    return text.strip(".,;:!?\"'()“”‘’…").lower()


def _merged(runs: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """A breath or a click a frame long doesn't split one pause in two."""
    out: list[tuple[float, float]] = []
    for a, b in runs:
        if out and a - out[-1][1] < 0.06:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def _closest(runs: list[tuple[float, float]], side: int, time: float) -> tuple[float, float]:
    return min(runs, key=lambda r: abs(r[side] - time))


def _edges(take: Take, rules: Rules, duration: float, limits: tuple[float, float], removable: list,
           quiet: Quiet | None, before: Take | None, after: Take | None) -> tuple[float, float]:
    start = max(limits[0], take.start - rules.handle_before)
    end = min(limits[1], duration, (take.end or take.start) + rules.handle_after)
    script = take.text.split()
    if not take.words or not script:
        return start, end
    first, last = take.words[0], take.words[-1]
    opener = _bare(first.text) == _bare(script[0])
    closer = _bare(last.text) == _bare(script[-1])
    if opener:
        # The take may have opened on a reading the recognizer lost, then been read again.
        start = max(start, first.start - PREROLL - rules.handle_before)
    if quiet is None:
        return start, end
    # An unheard opening sits somewhere before the first word heard, and a label ("Performance: the
    # load…") leaves a pause of its own after it.
    missing = 0 if opener else next((i for i, word in enumerate(script) if _bare(word) == _bare(first.text)), 1)
    labels = sum(1 for word in script[:missing] if word[-1] in ":,;—–")
    reach = REACH if opener else OPENER_REACH + 0.5 * max(0, missing - 1) + LABEL_PAUSE * labels
    bounds = ([limits[0]] + [b for a, b in removable if b <= first.start]
              + ([before.words[-1].start + PAUSE] if before is not None and before.words else []))
    low = max(bounds + [first.start - reach])
    if opener:
        runs = quiet.runs(low, max(first.start + PAUSE, first.end - 0.05), PAUSE)
        if not runs:
            # Speech right up to the word: Whisper timed it late, as it can a long one ("EventSourcingDB").
            runs = quiet.runs(max(bounds + [first.start - OPENER_REACH]), first.start, PAUSE)[-1:]
        found = _closest(runs, 1, first.start) if runs else None
    else:
        # The room is the longest silence before the labels' pauses.
        runs = _merged(quiet.runs(low, first.start, PAUSE))
        if labels and len(runs) > labels:
            runs = runs[:-labels]
        found = max(runs, key=lambda r: r[1] - r[0]) if runs else None
    if found:
        start = max(found[0], found[1] - rules.handle_before)
    following = (after.words[0].end - 0.05 if after.words else after.start) if after is not None else duration
    unheard = 0 if closer else next((i for i, word in enumerate(reversed(script)) if _bare(word) == _bare(last.text)), 1)
    tail_labels = sum(1 for word in script[len(script) - 1 - unheard:-1] if word[-1] in ":,;—–") if unheard else 0
    reach = TAIL_REACH if closer else OPENER_REACH + 0.5 * max(0, unheard - 1) + LABEL_PAUSE * tail_labels
    high = min([limits[1], duration, last.end + reach, following] + [a for a, b in removable if a >= last.start])
    runs = quiet.runs(last.start + PAUSE, high, PAUSE)
    if runs:
        if closer:
            long = [r for r in runs if r[1] - r[0] >= SENTENCE_PAUSE]
            a, b = _closest(long or runs, 0, last.end)
        else:
            # Unheard closing words ("…in a bucket: 1.6.") end at the sentence's own pause, past the labels'.
            runs = _merged(runs)
            if tail_labels and len(runs) > tail_labels:
                runs = runs[tail_labels:]
            a, b = max(runs, key=lambda r: r[1] - r[0])
        end = min(b, a + rules.handle_after)
    return start, end


def _neighbours(take: Take, log: TakeLog) -> tuple[Take | None, Take | None]:
    """The readings recorded right before and after this one, kept or not: its edges stay off them."""
    others = [t for t in log.takes if t.id != take.id and t.end is not None]
    before = max((t for t in others if t.start < take.start), key=lambda t: t.start, default=None)
    after = min((t for t in others if t.start > take.start), key=lambda t: t.start, default=None)
    return before, after


def _meet(edit: Edit, boundaries: list[float]) -> None:
    """Clips of one recording that overlap would play the overlap twice: the earlier one ends where the
    later one starts, which knows about an opening the recognizer missed."""
    clips = sorted(edit.clips, key=lambda c: (c.start, c.id))
    for left, right in zip(clips, clips[1:]):
        if left.end > right.start > left.start and not any(right.start < b <= left.end for b in boundaries):
            left.end = right.start


def _room_at(quiet: Quiet, time: float) -> tuple[float, float] | None:
    return next(((a, b) for a, b in quiet.runs(time - 3.0, time + 3.0, 0.02) if a - 0.011 <= time <= b + 0.011), None)


def _breathe(edit: Edit, quiet: Quiet | None, pause: float, boundaries: list[float], removable: list, only: set[int] | None = None) -> None:
    """Two takes joined by a cut get the pause a reader leaves between sentences, from the room's own
    silence on each side, never reaching into speech; handles alone leave a breathless quarter second."""
    if quiet is None:
        return
    timeline = edit.timeline()
    for left, right in zip(timeline, timeline[1:]):
        if abs(left.end - right.start) < 1e-6 or (only is not None and not {left.id, right.id} & only):
            continue
        after, before = _room_at(quiet, left.end), _room_at(quiet, right.start)
        played = (left.end - max(after[0], left.start) if after else 0.0) + (min(before[1], right.end) - right.start if before else 0.0)
        need = pause - played
        if need <= 0:
            continue
        later = [c.start for c in edit.clips if c.start >= left.end - 1e-6 and c is not left]
        limit_after = min([after[1] if after else left.end] + later + [a for a, b in removable if a >= left.end] + [b for b in boundaries if b > left.end])
        earlier = [c.end for c in edit.clips if c.end <= right.start + 1e-6 and c is not right]
        limit_before = max([before[0] if before else right.start] + earlier + [b for a, b in removable if b <= right.start] + [b for b in boundaries if b <= right.start])
        tail_room, head_room = max(0.0, limit_after - left.end), max(0.0, right.start - limit_before)
        head = min(head_room, need / 2)
        tail = min(tail_room, need - head)
        head = min(head_room, need - tail)
        left.end += tail
        right.start -= head


def _take_clips(edit: Edit, take: Take, rules: Rules, duration: float, removable: list, adlibs: list, limits: tuple[float, float],
                quiet: Quiet | None = None, neighbours: tuple[Take | None, Take | None] = (None, None)) -> None:
    start, end = _edges(take, rules, duration, limits, removable, quiet, *neighbours)
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


def auto_edit(log: TakeLog, duration: float, rules: Rules, boundaries: list[float] | None = None, quiet: Quiet | None = None) -> Edit:
    boundaries = sorted(boundaries or [])
    edit = Edit(source_duration=duration, crossfade_ms=rules.crossfade_ms, camera_crossfade_ms=rules.camera_crossfade_ms, rules=rules.__dict__.copy())
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
        _take_clips(edit, take, rules, duration, removable, adlibs, _limits(take, boundaries, duration), quiet, _neighbours(take, log))
    for start, end in kept_extra:
        for piece_start, piece_end in _subtract([(start - rules.handle_before, end + rules.handle_after)], removable):
            edit.clips.append(edit_clip(edit, piece_start, piece_end, None, "extra"))
    edit.clips.sort(key=lambda c: (c.start, c.id))
    _meet(edit, boundaries)
    _close_small_gaps(edit, rules.max_pause, removable, boundaries)
    _breathe(edit, quiet, rules.sentence_pause, boundaries, removable)
    edit.normalize()
    return edit


def update_sentences(edit: Edit, log: TakeLog, sentences: set[int], rules: Rules, duration: float, boundaries: list[float] | None = None,
                     quiet: Quiet | None = None) -> list[int]:
    """Puts the newest take (or the best, with keep="best") of each of these sentences in the edit
    and leaves the rest alone, so a pickup or a later recording doesn't undo hand edits elsewhere.
    Returns the sentences whose take changed."""
    grouped = _good_takes(log)
    edit.source_duration = duration
    updated = []
    for sentence in sorted(sentences):
        takes = grouped.get(sentence)
        if takes and use_take(edit, log, _choose(takes, rules.keep), rules, duration, boundaries, quiet):
            updated.append(sentence)
    return updated


def take_choices(log: TakeLog, sentence: int) -> list[Take]:
    """The takes a sentence can use: finished ones newest first, then the rejected ones (often fine
    but for one word the coach didn't like)."""
    finished = [t for t in log.takes if t.sentence == sentence and t.end is not None]
    complete = sorted((t for t in finished if t.status == COMPLETE), key=lambda t: -t.id)
    rejected = sorted((t for t in finished if t.status == REJECTED), key=lambda t: -t.id)
    return complete + rejected


def use_take(edit: Edit, log: TakeLog, take: Take, rules: Rules, duration: float, boundaries: list[float] | None = None,
             quiet: Quiet | None = None) -> bool:
    """Puts this take in its sentence's place. The clips of the take it replaces are kept aside and
    come back, trims and all, if that take is chosen again. Returns whether anything changed."""
    sentence = take.sentence
    current = [c for c in edit.clips if c.sentence == sentence]
    if current and all(c.take == take.id for c in current):
        return False
    for take_id in {c.take for c in current if c.take is not None}:
        edit.alternates[str(take_id)] = [asdict(c) for c in current if c.take == take_id]
    edit.clips = [c for c in edit.clips if c.sentence != sentence]
    saved = edit.alternates.pop(str(take.id), None)
    boundaries = sorted(boundaries or [])
    if saved:
        for data in saved:
            edit.clips.append(Clip(**{**data, "id": edit.next_id}))
            edit.next_id += 1
        # Its neighbours may have moved since its trims were kept: it mustn't play their audio twice.
        _meet(edit, boundaries)
    else:
        adlibs = [(m.start, m.end) for m in log.markers_of(kinds.ADLIB)]
        removable = _removable(log, rules)
        _take_clips(edit, take, rules, duration, removable, adlibs, _limits(take, boundaries, duration), quiet, _neighbours(take, log))
        _meet(edit, boundaries)
        _breathe(edit, quiet, rules.sentence_pause, boundaries, removable, {c.id for c in edit.clips if c.take == take.id})
    edit.clips.sort(key=lambda c: (c.start, c.id))
    edit.normalize()
    return True


def take_blocks(edit: Edit, log: TakeLog, rules: Rules, duration: float, boundaries: list[float] | None = None) -> list[tuple[float, float, list[Clip], Take | None]]:
    """The edit as whole takes, in the order it plays: each take in use with a second around it
    (room to pull a trim out), within its recording, and the clips kept from it. A clip that isn't a
    sentence's take is a block of its own."""
    boundaries = sorted(boundaries or [])
    takes = {t.id: t for t in log.takes}
    groups: dict[tuple, list[Clip]] = {}
    for clip in edit.timeline():
        key = (clip.sentence, clip.take) if clip.sentence is not None and clip.take in takes else ("clip", clip.id)
        groups.setdefault(key, []).append(clip)
    blocks = []
    for key, clips in groups.items():
        start, end = min(c.start for c in clips), max(c.end for c in clips)
        take = takes[key[1]] if key[0] != "clip" else None
        if take is not None:
            low, high = _limits(take, boundaries, duration)
            start = min(start, max(low, take.start - max(rules.handle_before, BLOCK_CONTEXT)))
            end = max(end, min(high, duration, (take.end or take.start) + max(rules.handle_after, BLOCK_CONTEXT)))
        blocks.append((start, end, clips, take))
    return blocks


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
