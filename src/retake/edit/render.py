from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import media
from .edl import Edit
from .exports import ass, ffmetadata
from .trim import offset_at


@dataclass(frozen=True)
class VideoFormat:
    container: str
    codec: str
    audio: str


VIDEO_FORMATS = {
    "mp4-h264": VideoFormat("mp4", "h264", "aac"),
    "mp4-hevc": VideoFormat("mp4", "hevc", "aac"),
    "mp4-av1": VideoFormat("mp4", "av1", "aac"),
    "webm-vp9": VideoFormat("webm", "vp9", "opus"),
    "mov-prores": VideoFormat("mov", "prores", "pcm"),
}

# Each codec's GPU encoder (None when NVENC has none) and CPU fallback.
VIDEO_ENCODERS = {
    "h264": ("h264_nvenc", "libx264"),
    "hevc": ("hevc_nvenc", "libx265"),
    "av1": ("av1_nvenc", "libsvtav1"),
    "vp9": (None, "libvpx-vp9"),
    "prores": (None, "prores_ks"),
}

QUALITIES = ("high", "balanced", "small")

AUDIO_FORMATS = {
    "flac": "flac",
    "wav": "wav",
    "mp3": "mp3",
    "opus": "opus",
    "aac": "m4a",
    "alac": "m4a",
    "vorbis": "ogg",
}


def video_encoder(codec: str, gpu: bool = True) -> str:
    accelerated, software = VIDEO_ENCODERS[codec]
    if gpu and accelerated and media.encoder_works(accelerated):
        return accelerated
    return software


def video_output_name(settings: dict) -> str:
    fmt = VIDEO_FORMATS[settings["video_format"]]
    stem = "video"
    if fmt.container == "mp4" and fmt.codec != "h264":
        stem += f"-{fmt.codec}"
    if int(settings.get("video_size") or 0):
        stem += f"-{int(settings['video_size'])}p"
    return f"{stem}.{fmt.container}"


def audio_output_name(settings: dict) -> str:
    codec = settings["audio_format"]
    return ("narration-alac" if codec == "alac" else "narration") + "." + AUDIO_FORMATS[codec]


def scaled(width: int, height: int, short_side: int) -> tuple[int, int]:
    """The picture's size with its short side at most short_side (never upscaled), in even pixels."""
    factor = min(1.0, short_side / min(width, height)) if short_side else 1.0
    return max(2, round(width * factor / 2) * 2), max(2, round(height * factor / 2) * 2)


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
    video: str = ""
    quality: str = "high"
    size: int = 0
    fps: float = 0.0
    gpu: bool = True
    audio: str = "flac"
    audio_bitrate: str = "192k"
    sample_rate: int = 0
    channels: int = 0
    depth: int = 24
    loudness: float = 0.0
    chapters: list[tuple[float, str]] = field(default_factory=list)
    title: str = ""
    captions: list[tuple[float, float, str]] = field(default_factory=list)
    caption_line: int = 42
    caption_lines: int = 2
    progress: Callable[[float], None] = lambda fraction: None

    @property
    def with_video(self) -> bool:
        return bool(self.video)


def video_job(edit: Edit, sources: list[Source], out_dir: Path, settings: dict, **extra) -> RenderJob:
    """A video export with the choices remembered from the Video export dialog (config [export])."""
    fmt = VIDEO_FORMATS[settings["video_format"]]
    return RenderJob(
        edit, sources, out_dir / video_output_name(settings), video=fmt.codec, audio=fmt.audio,
        quality=settings["video_quality"], size=int(settings.get("video_size") or 0), fps=float(settings.get("video_fps") or 0),
        audio_bitrate=settings["video_audio_bitrate"], loudness=float(settings.get("loudness") or 0),
        caption_line=int(settings["caption_line"]), caption_lines=int(settings["caption_lines"]), **extra,
    )


def audio_job(edit: Edit, sources: list[Source], out_dir: Path, settings: dict, **extra) -> RenderJob:
    return RenderJob(
        edit, sources, out_dir / audio_output_name(settings), audio=settings["audio_format"],
        audio_bitrate=settings["audio_bitrate"], sample_rate=int(settings.get("audio_rate") or 0),
        channels=int(settings.get("audio_channels") or 0), depth=int(settings.get("audio_depth") or 24),
        loudness=float(settings.get("loudness") or 0), **extra,
    )


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


def pieces(job: RenderJob, fps: float = 0.0) -> list[Piece]:
    """The edit's clips in play order, split where they cross from one recording to the next.
    With video, each piece ends on the output frame grid: video cuts land on whole frames, and
    rounding each piece on its own would add up to seconds of drift against the script timing."""
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


def build_inputs(job: RenderJob, batch: list[Piece], info: VideoInfo | None = None, captions: Path | None = None, offset: float = 0.0) -> tuple[list[str], str]:
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
    concat = f"{''.join(labels)}concat=n={len(batch)}:v={1 if job.with_video else 0}:a=1"
    if not job.with_video:
        parts.append(concat + "[aout]")
    elif captions is None:
        parts.append(concat + "[vout][aout]")
    else:
        # The captions are timed on the whole edit; this batch starts `offset` into it.
        parts.append(concat + "[vcat][aout]")
        parts.append(f"[vcat]setpts=PTS+{offset:.6f}/TB,ass=filename={captions},setpts=PTS-STARTPTS[vout]")
    return inputs, ";\n".join(parts)


def _quality_args(encoder: str, quality: str) -> list[str]:
    level = QUALITIES.index(quality) if quality in QUALITIES else 0
    if encoder == "h264_nvenc":
        return ["-preset", "p5", "-rc", "vbr", "-cq", str((19, 23, 27)[level]), "-b:v", "0"]
    # hvc1 tagging lets Apple players and most editors open H.265 in MP4.
    if encoder == "hevc_nvenc":
        return ["-preset", "p5", "-rc", "vbr", "-cq", str((21, 25, 29)[level]), "-b:v", "0", "-tag:v", "hvc1"]
    if encoder == "libx265":
        return ["-preset", "medium", "-crf", str((20, 23, 26)[level]), "-tag:v", "hvc1"]
    if encoder == "av1_nvenc":
        return ["-preset", "p5", "-rc", "vbr", "-cq", str((24, 30, 36)[level]), "-b:v", "0"]
    if encoder == "libsvtav1":
        return ["-preset", "8", "-crf", str((26, 32, 38)[level])]
    if encoder == "libvpx-vp9":
        return ["-crf", str((28, 33, 38)[level]), "-b:v", "0", "-deadline", "good", "-cpu-used", "4", "-row-mt", "1"]
    if encoder == "prores_ks":
        return ["-profile:v", str((3, 2, 1)[level]), "-vendor", "apl0"]
    return ["-preset", "veryfast", "-crf", str((18, 21, 24)[level])]


def _video_args(job: RenderJob) -> list[str]:
    encoder = video_encoder(job.video, job.gpu)
    pixels = "yuv422p10le" if job.video == "prores" else "yuv420p"
    return ["-c:v", encoder, *_quality_args(encoder, job.quality), "-pix_fmt", pixels]


def _audio_args(job: RenderJob) -> list[str]:
    deep = job.depth >= 24
    return {
        "flac": ["-c:a", "flac", "-sample_fmt", "s32" if deep else "s16", "-bits_per_raw_sample", "24" if deep else "16"],
        "alac": ["-c:a", "alac", "-sample_fmt", "s32p" if deep else "s16p", "-bits_per_raw_sample", "24" if deep else "16"],
        "wav": ["-c:a", "pcm_s24le" if deep else "pcm_s16le"],
        "pcm": ["-c:a", "pcm_s24le" if deep else "pcm_s16le"],
        "mp3": ["-c:a", "libmp3lame", "-b:a", job.audio_bitrate, "-id3v2_version", "3"],
        "opus": ["-c:a", "libopus", "-b:a", job.audio_bitrate],
        "aac": ["-c:a", "aac", "-b:a", job.audio_bitrate],
        "vorbis": ["-c:a", "libvorbis", "-b:a", job.audio_bitrate],
    }[job.audio]


def _video_info(job: RenderJob) -> VideoInfo | None:
    videos = [source.video for source in job.sources if source.video is not None]
    if not job.with_video or not videos:
        return None
    probes = {video: media.probe(video) for video in dict.fromkeys(videos)}
    first = probes[videos[0]]
    width, height = scaled(first.width or 1920, first.height or 1080, job.size)
    fps = first.fps or 30.0
    if job.fps and job.fps < fps:
        fps = job.fps
    return VideoInfo({video: info.duration for video, info in probes.items()}, fps, width, height)


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
        captions = None
        if info and job.captions:
            captions = scratch / "captions.ass"
            captions.write_text(ass(job.captions, info.width, info.height, job.caption_line, job.caption_lines), encoding="utf-8")
        batches = [planned[i:i + BATCH] for i in range(0, len(planned), BATCH)]
        outputs = []
        done = 0.0
        for number, batch in enumerate(batches):
            part = scratch / (f"part{number:04d}.mkv" if job.with_video else f"part{number:04d}.wav")
            batch_total = sum(piece.duration for piece in batch)
            offset = done

            def report(fraction: float, offset=offset, batch_total=batch_total) -> None:
                job.progress(min(0.95, (offset + fraction * batch_total) / max(total, 0.001)))

            _render_part(job, batch, part, info, scratch, report, captions, offset)
            outputs.append(part)
            done += batch_total
        _finish(job, outputs, total, scratch)
    job.progress(1.0)
    return job.output


def _render_part(job: RenderJob, batch: list[Piece], part: Path, info: VideoInfo | None, scratch: Path, progress,
                 captions: Path | None = None, offset: float = 0.0) -> None:
    inputs, graph = build_inputs(job, batch, info, captions, offset)
    graph_file = scratch / f"{part.stem}.txt"
    graph_file.write_text(graph)
    command = [media.ffmpeg(), "-y", "-v", "error", "-progress", "pipe:1", "-nostats", *inputs, "-/filter_complex", str(graph_file)]
    if job.with_video:
        command += ["-map", "[vout]", "-map", "[aout]", *_video_args(job), "-c:a", "pcm_s24le"]
    else:
        command += ["-map", "[aout]", "-c:a", "pcm_f32le"]
    command.append(str(part))
    _run(command, sum(piece.duration for piece in batch), progress)


def _measure_loudness(listing: Path, target: float) -> dict:
    command = [media.ffmpeg(), "-hide_banner", "-nostats", "-f", "concat", "-safe", "0", "-i", str(listing), "-vn",
               "-af", f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"]
    errors = subprocess.run(command, capture_output=True, text=True).stderr
    return json.loads(errors[errors.rindex("{"):errors.rindex("}") + 1])


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
    if job.loudness:
        # Two passes: measuring first lets loudnorm apply one steady gain instead of riding the level.
        measured = _measure_loudness(listing, job.loudness)
        command += ["-af", (
            f"loudnorm=I={job.loudness}:TP=-1.5:LRA=11:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:offset={measured['target_offset']}:linear=true"
        )]
    job.progress(0.97)
    # loudnorm works at 192 kHz, so the rate is always set rather than inherited.
    rate = job.sample_rate or next((media.probe(s.audio).sample_rate for s in job.sources), 0) or 48000
    command += ["-ar", str(rate)]
    if job.channels:
        command += ["-ac", str(job.channels)]
    if job.with_video:
        command += ["-map", "0:v", "-map", "0:a", "-c:v", "copy"]
    else:
        command += ["-map", "0:a"]
    command += _audio_args(job)
    if job.output.suffix.lower() in (".mp4", ".mov", ".m4a"):
        command += ["-movflags", "+faststart"]
    if metadata_index is not None:
        command += ["-map_metadata", str(metadata_index), "-map_chapters", str(metadata_index)]
    command.append(str(job.output))
    _run(command, 0.0, lambda fraction: None)


def _run(command: list[str], total: float, progress: Callable[[float], None]) -> None:
    # stderr goes to a file: encoders like SVT-AV1 print a banner whatever the log level, and an
    # unread pipe would stall FFmpeg once it filled.
    with tempfile.TemporaryFile(mode="w+") as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, text=True)
        for line in process.stdout:
            if line.startswith("out_time_us=") and total > 0:
                try:
                    progress(min(1.0, int(line.split("=")[1]) / 1_000_000 / total))
                except ValueError:
                    pass
        process.wait()
        errors.seek(0)
        lines = [line for line in errors.read().splitlines() if line.strip() and not line.startswith(("Svt[", "SvtMalloc["))]
    if process.returncode != 0:
        raise RuntimeError(lines[-1] if lines else f"ffmpeg exited with {process.returncode}")
    progress(1.0)


def render_with_fallback(job: RenderJob) -> Path:
    try:
        return render(job)
    except RuntimeError:
        if job.with_video and job.gpu and video_encoder(job.video) != VIDEO_ENCODERS[job.video][1]:
            job.gpu = False
            return render(job)
        raise
