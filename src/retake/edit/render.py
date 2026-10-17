from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import media
from .edl import Edit
from .exports import ffmetadata
from .trim import offset_at

AUDIO_CODECS = {
    "flac": ["-c:a", "flac"],
    "wav": ["-c:a", "pcm_s24le"],
    "opus": ["-c:a", "libopus", "-b:a", "128k"],
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2", "-id3v2_version", "3"],
}


@dataclass
class Source:
    """A recording the edit reads from: where it sits on the edit's timeline and its media."""

    audio: Path
    start: float = 0.0
    duration: float = float("inf")
    video: Path | None = None
    video_offset: float = 0.0
    segments: list = field(default_factory=list)

    @property
    def end(self) -> float:
        return self.start + self.duration

    def offset_at(self, local: float) -> float:
        return offset_at(self.segments, self.video_offset, local)

    def boundaries(self) -> list[float]:
        """Where the video's time map changes, on the edit's timeline."""
        return [self.start + s.audio_end for s in self.segments[:-1]]


@dataclass
class RenderJob:
    edit: Edit
    sources: list[Source]
    output: Path
    with_video: bool = False
    encoder: str = "auto"
    normalize: bool = False
    loudness: float = -16.0
    chapters: list[tuple[float, str]] = field(default_factory=list)
    title: str = ""
    progress: Callable[[float], None] = lambda fraction: None


@dataclass
class Piece:
    source: Source
    local: float
    duration: float


@dataclass
class VideoInfo:
    durations: dict[Path, float]
    fps: float = 30.0
    width: int = 1920
    height: int = 1080


BATCH = 40


def frame_aligned(segments: list[tuple[float, float]], fps: float) -> list[tuple[float, float]]:
    # Video cuts land on whole frames, so every clip is sized to end on the output frame grid;
    # rounding each clip on its own would add up to seconds of drift against the script timing.
    aligned = []
    elapsed = placed = 0.0
    for start, end in segments:
        elapsed += end - start
        boundary = round(elapsed * fps) / fps
        if boundary > placed:
            aligned.append((start, start + boundary - placed))
            placed = boundary
    return aligned


def pieces(job: RenderJob, fps: float = 0.0) -> list[Piece]:
    """The edit's clips in play order, split where they cross from one recording to the next,
    and sized on the output frame grid when there is video (see frame_aligned)."""
    split: list[tuple[Source, float, float]] = []
    for clip in job.edit.timeline():
        for source in job.sources:
            start, end = max(clip.start, source.start), min(clip.end, source.end)
            for cut in source.boundaries() if job.with_video else []:
                if start < cut < end:
                    split.append((source, start, cut))
                    start = cut
            if end - start > 1e-6:
                split.append((source, start, end))
    if fps <= 0:
        return [Piece(source, start - source.start, end - start) for source, start, end in split]
    result = []
    elapsed = placed = 0.0
    for source, start, end in split:
        elapsed += end - start
        boundary = round(elapsed * fps) / fps
        if boundary > placed:
            result.append(Piece(source, start - source.start, boundary - placed))
            placed = boundary
    return result


def build_inputs(job: RenderJob, batch: list[Piece], info: VideoInfo | None = None) -> tuple[list[str], str]:
    fade = max(0.0, job.edit.crossfade_ms / 1000.0)
    fps = info.fps if info else 30.0
    inputs: list[str] = []
    parts: list[str] = []
    labels: list[str] = []
    count = 0
    for index, piece in enumerate(batch):
        duration = piece.duration
        inputs += ["-ss", f"{piece.local:.4f}", "-t", f"{duration:.4f}", "-i", str(piece.source.audio)]
        chain = f"[{count}:a]asetpts=PTS-STARTPTS"
        count += 1
        if fade > 0 and duration > fade * 3:
            chain += f",afade=t=in:d={fade:.3f},afade=t=out:st={duration - fade:.4f}:d={fade:.3f}"
        parts.append(chain + f"[a{index}]")
        if job.with_video:
            video = piece.source.video
            if video is None:
                inputs += ["-f", "lavfi", "-t", f"{duration + 1 / fps:.4f}", "-i", f"color=c=black:s={info.width}x{info.height}:r={fps:.6f}"]
                chain = f"[{count}:v]setpts=PTS-STARTPTS,trim=end_frame={round(duration * fps)}"
            else:
                video_start = piece.local - piece.source.offset_at(piece.local)
                lead = max(0.0, -video_start)
                seek = max(0.0, video_start)
                length = max(0.04, min(duration - lead, info.durations.get(video, duration) - seek))
                tail = max(0.0, duration - lead - length) + 2 / fps
                inputs += ["-ss", f"{seek:.4f}", "-t", f"{length:.4f}", "-i", str(video)]
                chain = f"[{count}:v]setpts=PTS-STARTPTS,fps={fps:.6f},scale={info.width}:{info.height}:force_original_aspect_ratio=decrease,pad={info.width}:{info.height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
                chain += f",tpad=start_mode=clone:start_duration={lead:.4f}:stop_mode=clone:stop_duration={tail:.4f}"
                chain += f",trim=end_frame={round(duration * fps)}"
            count += 1
            parts.append(chain + f"[v{index}]")
            labels.append(f"[v{index}][a{index}]")
        else:
            labels.append(f"[a{index}]")
    parts.append(f"{''.join(labels)}concat=n={len(batch)}:v={1 if job.with_video else 0}:a=1" + ("[vout][aout]" if job.with_video else "[aout]"))
    return inputs, ";\n".join(parts)


def _video_encoder(choice: str) -> list[str]:
    available = media.encoders()
    if choice == "auto":
        choice = "h264_nvenc" if "h264_nvenc" in available else "libx264"
    if choice == "hevc":
        choice = "hevc_nvenc" if "hevc_nvenc" in available else "libx265"
    if choice == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"]
    # hvc1 tagging lets Apple players and most editors open H.265 in MP4.
    if choice == "hevc_nvenc":
        return ["-c:v", "hevc_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0", "-tag:v", "hvc1"]
    if choice == "libx265":
        return ["-c:v", "libx265", "-preset", "medium", "-crf", "20", "-tag:v", "hvc1"]
    if choice == "h264_vaapi":
        return ["-vaapi_device", "/dev/dri/renderD128", "-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi", "-qp", "20"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]


def _video_info(job: RenderJob) -> VideoInfo | None:
    videos = [source.video for source in job.sources if source.video is not None]
    if not job.with_video or not videos:
        return None
    probes = {video: media.probe(video) for video in dict.fromkeys(videos)}
    first = probes[videos[0]]
    return VideoInfo({video: info.duration for video, info in probes.items()}, first.fps or 30.0, first.width or 1920, first.height or 1080)


def render(job: RenderJob) -> Path:
    if job.with_video and not any(source.video for source in job.sources):
        raise ValueError("there is no video to render")
    info = _video_info(job)
    planned = pieces(job, info.fps if info else 0.0)
    if not planned:
        raise ValueError("the edit has no clips")
    total = sum(piece.duration for piece in planned)
    job.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="retake-render-") as scratch_name:
        scratch = Path(scratch_name)
        batches = [planned[i:i + BATCH] for i in range(0, len(planned), BATCH)]
        outputs = []
        done = 0.0
        for number, batch in enumerate(batches):
            part = scratch / (f"part{number:04d}.mkv" if job.with_video else f"part{number:04d}.wav")
            batch_total = sum(piece.duration for piece in batch)
            offset = done

            def report(fraction: float, offset=offset, batch_total=batch_total) -> None:
                job.progress(min(0.98, (offset + fraction * batch_total) / max(total, 0.001)))

            _render_part(job, batch, part, info, scratch, report)
            outputs.append(part)
            done += batch_total
        _finish(job, outputs, total, scratch)
    job.progress(1.0)
    return job.output


def _render_part(job: RenderJob, batch: list[Piece], part: Path, info: VideoInfo | None, scratch: Path, progress) -> None:
    inputs, graph = build_inputs(job, batch, info)
    graph_file = scratch / f"{part.stem}.txt"
    graph_file.write_text(graph)
    command = [media.ffmpeg(), "-y", "-v", "error", "-progress", "pipe:1", "-nostats", *inputs, "-/filter_complex", str(graph_file)]
    if job.with_video:
        command += ["-map", "[vout]", "-map", "[aout]"] + _video_encoder(job.encoder) + ["-pix_fmt", "yuv420p", "-c:a", "pcm_s24le"]
    else:
        command += ["-map", "[aout]", "-c:a", "pcm_f32le"]
    command.append(str(part))
    _run(command, sum(piece.duration for piece in batch), progress)


def _finish(job: RenderJob, parts: list[Path], total: float, scratch: Path) -> None:
    listing = scratch / "parts.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in parts))
    command = [media.ffmpeg(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing)]
    metadata_index = None
    if job.chapters or job.title:
        meta = scratch / "chapters.txt"
        meta.write_text(ffmetadata(job.chapters, total, job.title))
        command += ["-i", str(meta)]
        metadata_index = 1
    if job.normalize:
        command += ["-af", f"loudnorm=I={job.loudness}:TP=-1.5:LRA=11"]
    if job.with_video:
        command += ["-map", "0:v", "-map", "0:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    else:
        fmt = job.output.suffix.lstrip(".").lower()
        command += ["-map", "0:a"] + AUDIO_CODECS.get(fmt, ["-c:a", "flac"])
    if metadata_index is not None:
        command += ["-map_metadata", str(metadata_index), "-map_chapters", str(metadata_index)]
    command.append(str(job.output))
    _run(command, 0.0, lambda fraction: None)


def _run(command: list[str], total: float, progress: Callable[[float], None]) -> None:
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in process.stdout:
        if line.startswith("out_time_us=") and total > 0:
            try:
                progress(min(1.0, int(line.split("=")[1]) / 1_000_000 / total))
            except ValueError:
                pass
    _, errors = process.communicate()
    if process.returncode != 0:
        raise RuntimeError(errors.strip().splitlines()[-1] if errors.strip() else f"ffmpeg exited with {process.returncode}")
    progress(1.0)


def render_with_fallback(job: RenderJob) -> Path:
    try:
        return render(job)
    except RuntimeError:
        if job.with_video and job.encoder in ("auto", "h264_nvenc", "hevc", "hevc_nvenc"):
            job.encoder = "libx265" if job.encoder.startswith("hevc") else "libx264"
            return render(job)
        raise
