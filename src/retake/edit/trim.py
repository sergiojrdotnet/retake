from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import media


@dataclass
class Segment:
    """A stretch of a part's audio and where its video now sits: video time = audio time - offset."""

    audio_start: float
    audio_end: float
    offset: float

    def as_dict(self) -> dict:
        return {"audio_start": round(self.audio_start, 4), "audio_end": round(self.audio_end, 4), "offset": round(self.offset, 4)}

    @classmethod
    def from_dict(cls, data: dict) -> Segment:
        return cls(float(data["audio_start"]), float(data["audio_end"]), float(data["offset"]))


def offset_at(segments: list[Segment], offset: float, local: float) -> float:
    """The video offset at a moment of the part's audio; untrimmed video has a single one."""
    for segment in segments:
        if local < segment.audio_end:
            return segment.offset
    return segments[-1].offset if segments else offset


def keyframes(video: Path) -> list[float]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True,
    )
    times = []
    for line in result.stdout.splitlines():
        fields = line.split(",")
        if len(fields) >= 2 and "K" in fields[1]:
            try:
                times.append(float(fields[0]))
            except ValueError:
                continue
    return sorted(times)


@dataclass
class Cut:
    video_in: float
    video_out: float
    audio_start: float
    audio_end: float


def plan(audio_duration: float, offset: float, video_duration: float, pauses: list[tuple[float, float]],
         keys: list[float], margin: float = 1.0, shortest_pause: float = 4.0) -> list[Cut]:
    """The stretches of video to keep: what plays against the audio, minus long pauses.

    Each kept stretch starts on the keyframe at or before where it's needed (a lossless cut can't start
    elsewhere) and keeps a margin around the pauses it skips."""
    keep: list[list[float]] = [[0.0, audio_duration]]
    for start, end in sorted(pauses):
        if end - start < shortest_pause:
            continue
        cut_start, cut_end = start + margin, end - margin
        updated = []
        for a, b in keep:
            if cut_end <= a or cut_start >= b:
                updated.append([a, b])
                continue
            if cut_start > a:
                updated.append([a, cut_start])
            if cut_end < b:
                updated.append([cut_end, b])
        keep = updated
    cuts = []
    for a, b in keep:
        wanted_in = max(0.0, a - offset)
        wanted_out = min(video_duration, b - offset)
        if wanted_out <= wanted_in:
            continue
        video_in = max((k for k in keys if k <= wanted_in + 1e-3), default=0.0)
        if cuts and video_in < cuts[-1].video_out:
            # Keyframes too far apart to skip this pause: keep the video running through it.
            cuts[-1].video_out, cuts[-1].audio_end = wanted_out, b
            continue
        cuts.append(Cut(video_in, wanted_out, video_in + offset, b))
    return cuts


def apply(video: Path, cuts: list[Cut], offset: float) -> list[Segment]:
    """Rewrites the video with only the kept stretches (a stream copy, no re-encoding) and returns
    the segments that map the part's audio onto the new file."""
    with tempfile.TemporaryDirectory(prefix="retake-trim-") as scratch_name:
        scratch = Path(scratch_name)
        listing = scratch / "keep.txt"
        listing.write_text("".join(f"file '{video}'\ninpoint {c.video_in:.6f}\noutpoint {c.video_out:.6f}\n" for c in cuts))
        # Written beside the original so the final rename stays on the same drive.
        output = video.with_name(f".{video.stem}.trimmed{video.suffix}")
        result = subprocess.run(
            [media.ffmpeg(), "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-map", "0", "-c", "copy", "-copyinkf", str(output)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            output.unlink(missing_ok=True)
            raise RuntimeError(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "ffmpeg failed")
        output.replace(video)
    segments = []
    position = 0.0
    for cut in cuts:
        # Audio time t in this stretch was at video time t - offset; it now sits `position` into the file.
        segments.append(Segment(cut.audio_start, cut.audio_end, offset + cut.video_in - position))
        position += cut.video_out - cut.video_in
    return segments


def trim(video: Path, audio_duration: float, offset: float, pauses: list[tuple[float, float]]) -> list[Segment] | None:
    """Drops the waiting before a part and its long pauses from the video; None when nothing worth cutting."""
    duration = media.probe(video).duration
    cuts = plan(audio_duration, offset, duration, pauses, keyframes(video))
    kept = sum(c.video_out - c.video_in for c in cuts)
    if not cuts or duration - kept < 2.0:
        return None
    return apply(video, cuts, offset)
