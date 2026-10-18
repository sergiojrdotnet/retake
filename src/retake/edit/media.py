from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np


@dataclass
class MediaInfo:
    duration: float
    has_video: bool
    has_audio: bool
    width: int = 0
    height: int = 0
    fps: float = 30.0
    sample_rate: int = 0
    channels: int = 0


def ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise FileNotFoundError("ffmpeg is not installed")
    return path


def probe(path: Path) -> MediaInfo:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fps = 30.0
    if video and video.get("avg_frame_rate", "0/0") not in ("0/0", ""):
        num, den = video["avg_frame_rate"].split("/")
        fps = float(num) / float(den) if float(den) else 30.0
    if video and not 1.0 <= fps <= 240.0:
        fps = measured_fps(path) or 30.0
    return MediaInfo(
        duration=float(data.get("format", {}).get("duration", 0.0) or 0.0),
        has_video=video is not None,
        has_audio=audio is not None,
        width=int(video.get("width", 0)) if video else 0,
        height=int(video.get("height", 0)) if video else 0,
        fps=fps,
        sample_rate=int(audio.get("sample_rate", 0)) if audio else 0,
        channels=int(audio.get("channels", 0)) if audio else 0,
    )


COMMON_RATES = (23.976, 24.0, 25.0, 29.97, 30.0, 48.0, 50.0, 59.94, 60.0, 90.0, 120.0, 240.0)


def measured_fps(path: Path, seconds: float = 6.0) -> float | None:
    """The frame rate from the first frames' timestamps. Phone recordings (scrcpy's MKV) carry a
    millisecond time base that FFmpeg reports as 1000 fps."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time", "-of", "csv=p=0", "-read_intervals", f"%+{seconds}", str(path)],
        capture_output=True, text=True,
    )
    stamps = sorted(float(line.split(",")[0]) for line in result.stdout.split() if line.split(",")[0] not in ("", "N/A"))
    if len(stamps) < 10 or stamps[-1] <= stamps[0]:
        return None
    fps = (len(stamps) - 1) / (stamps[-1] - stamps[0])
    nearest = min(COMMON_RATES, key=lambda rate: abs(rate - fps))
    return nearest if abs(nearest - fps) / nearest < 0.03 else round(fps, 3)


def first_timestamp(path: Path, stream: str) -> float | None:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", "packet=pts_time", "-of", "csv=p=0", "-read_intervals", "%+#1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.split()[0].split(",")[0])
    except (IndexError, ValueError):
        return None


def prepare_phone_video(path: Path) -> None:
    """Rewrites a scrcpy recording into a file every player and cut handles cleanly.

    scrcpy marks none of its audio packets as keyframes: a stream copy then drops the whole track, and
    Qt's demuxer complains on every seek. The audio is re-encoded to FLAC, lossless from the decoded
    AAC, where every packet is a keyframe. scrcpy also sometimes stamps the video with the camera's own
    clock (seconds since the phone booted) while the audio starts at zero; the video is moved to
    start where the audio does."""
    video, audio = first_timestamp(path, "v:0"), first_timestamp(path, "a:0")
    # MP4 takes ALAC as its lossless audio; MKV takes FLAC.
    audio_codec = "alac" if path.suffix.lower() in (".mp4", ".mov") else "flac"
    command = [ffmpeg(), "-v", "error", "-y", "-i", str(path), "-map", "0", "-c:v", "copy", "-c:a", audio_codec]
    if video is not None and audio is not None and abs(video - audio) >= 1.0:
        command += ["-bsf:v", f"setts=pts=PTS-STARTPTS+{audio:.6f}/TB:dts=DTS-STARTDTS+{audio:.6f}/TB"]
    prepared = path.with_name(f".{path.stem}.prepared{path.suffix}")
    result = subprocess.run(command + [str(prepared)], capture_output=True, text=True)
    if result.returncode != 0:
        prepared.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "ffmpeg failed")
    prepared.replace(path)


@cache
def encoders() -> frozenset[str]:
    try:
        output = subprocess.run([ffmpeg(), "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()
    names = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6:
            names.add(parts[1])
    return frozenset(names)


@cache
def encoder_works(name: str) -> bool:
    """Whether this machine can actually use the encoder: a GPU encoder is listed whenever FFmpeg was
    built with it, even without a GPU (or one too old for the codec) to run it."""
    if name not in encoders():
        return False
    command = [ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "color=s=256x256:d=0.1", "-frames:v", "2", "-c:v", name, "-f", "null", "-"]
    try:
        return subprocess.run(command, capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def decode_mono(path: Path, rate: int = 8000, start: float = 0.0, duration: float | None = None) -> np.ndarray:
    command = [ffmpeg(), "-v", "error", "-ss", f"{start:.3f}"]
    if duration is not None:
        command += ["-t", f"{duration:.3f}"]
    command += ["-i", str(path), "-vn", "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"]
    result = subprocess.run(command, capture_output=True, check=True)
    return np.frombuffer(result.stdout, dtype=np.float32)


def read_first_frame_timestamp(video: Path) -> float | None:
    stamp = video.with_name(video.name + ".ts")
    if not stamp.exists():
        return None
    try:
        monotonic_us = int(stamp.read_text().split()[0])
    except (ValueError, IndexError):
        return None
    return monotonic_us / 1_000_000


def cross_correlate(reference: np.ndarray, other: np.ndarray, rate: int, max_shift: float = 3.0) -> tuple[float, float]:
    length = min(len(reference), len(other))
    if length < rate:
        return 0.0, 0.0
    a = reference[:length] - reference[:length].mean()
    b = other[:length] - other[:length].mean()
    size = 1 << (2 * length - 1).bit_length()
    spectrum = np.fft.rfft(a, size) * np.conj(np.fft.rfft(b, size))
    correlation = np.fft.irfft(spectrum, size)
    limit = int(max_shift * rate)
    candidates = np.concatenate([correlation[-limit:], correlation[:limit + 1]])
    best = int(np.argmax(candidates)) - limit
    norm = float(np.sqrt((a * a).sum() * (b * b).sum())) or 1.0
    return best / rate, float(candidates[best + limit] / norm)


def estimate_offset(audio: Path, video: Path, audio_t0: float | None, window: float = 12.0, video_t0: float | None = None) -> tuple[float, str]:
    """How far the video starts after the audio (video time = audio time - offset).

    The recorders' start times give a first guess; matching the video's own soundtrack against the
    audio refines it. That match runs on several short stretches, skips silent ones (a pause would
    swamp a single long window) and is trusted only when the stretches agree."""
    expected = 0.0
    method = "none"
    first_frame = read_first_frame_timestamp(video)
    if first_frame is None:
        first_frame = video_t0
    if first_frame is not None and audio_t0 is not None:
        expected = first_frame - audio_t0
        method = "timestamp"
    try:
        if not probe(video).has_audio:
            return expected, method
        rate = 8000
        span = 240.0
        reference = decode_mono(audio, rate, 0.0, span)
        other = decode_mono(video, rate, 0.0, span)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return expected, method
    found: list[float] = []
    start = max(0.0, expected) + 0.5
    while start + window <= len(reference) / rate and len(found) < 10:
        a = reference[int(start * rate):int((start + window) * rate)]
        video_start = start - expected
        b = other[int(video_start * rate):int((video_start + window) * rate)] if video_start >= 0 else np.zeros(0, dtype=np.float32)
        start += window
        if len(b) < rate or float(np.sqrt(np.mean(a * a))) < 1e-3 or float(np.sqrt(np.mean(b * b))) < 1e-4:
            continue
        shift, confidence = cross_correlate(a, b, rate)
        if confidence >= 0.15:
            found.append(expected + shift)
    if found:
        middle = float(np.median(found))
        agreeing = [value for value in found if abs(value - middle) < 0.05]
        if len(agreeing) >= max(2, len(found) // 2):
            return float(np.median(agreeing)), "correlation"
    return expected, method


def peaks(path: Path, per_second: int = 100, cache_dir: Path | None = None) -> np.ndarray:
    import soundfile

    cache_file = None
    if cache_dir is not None:
        stat = path.stat()
        cache_file = cache_dir / f"{path.stem}-{int(stat.st_mtime)}-{stat.st_size}-{per_second}.npy"
        if cache_file.exists():
            return np.load(cache_file)
    with soundfile.SoundFile(path) as source:
        block = max(1, int(source.samplerate / per_second))
        values = []
        while True:
            data = source.read(block * per_second * 10, dtype="float32", always_2d=True)
            if not len(data):
                break
            mono = np.abs(data).max(axis=1)
            usable = len(mono) - len(mono) % block
            if usable:
                values.append(mono[:usable].reshape(-1, block).max(axis=1))
            if len(mono) - usable:
                values.append(np.array([mono[usable:].max()]))
    result = np.concatenate(values) if values else np.zeros(0, dtype=np.float32)
    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        np.save(cache_file, result.astype(np.float32))
    return result.astype(np.float32)


def thumbnails(video: Path, directory: Path, every: float = 2.0, height: int = 72) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    existing = sorted(directory.glob("thumb-*.jpg"))
    if existing:
        return existing
    subprocess.run(
        [ffmpeg(), "-v", "error", "-i", str(video), "-vf", f"fps=1/{every},scale=-2:{height}", "-q:v", "6", str(directory / "thumb-%05d.jpg")],
        check=True, capture_output=True,
    )
    return sorted(directory.glob("thumb-*.jpg"))
