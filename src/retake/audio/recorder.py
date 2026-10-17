from __future__ import annotations

import json
import math
import os
import queue
import subprocess
import threading
import time
from multiprocessing.connection import Connection, Listener
from pathlib import Path

import numpy as np

from ..child import exit_quietly

ENGINE_RATE = 16000
ENGINE_CHUNK = 480
LEVEL_INTERVAL = 0.05


def pipewire_sources() -> list[dict]:
    try:
        output = subprocess.run(["pactl", "-f", "json", "list", "sources"], capture_output=True, text=True, timeout=5).stdout
        sources = json.loads(output or "[]")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return []
    try:
        default = subprocess.run(["pactl", "get-default-source"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        default = ""
    result = []
    for source in sources:
        name = source.get("name", "")
        if name.endswith(".monitor"):
            continue
        spec = source.get("sample_specification", "")
        result.append({
            "name": name,
            "description": source.get("description", name),
            "channels": int(spec.split("ch")[0].split()[-1]) if "ch" in spec else 2,
            "default": name == default,
        })
    return result


class Recorder:
    def __init__(self, control: Connection, address: str, authkey: bytes):
        self.control = control
        self.engine: Connection | None = None
        self.listener = Listener(address, family="AF_UNIX", authkey=authkey)
        self.send_lock = threading.Lock()
        self.chunks: queue.Queue = queue.Queue(maxsize=2000)
        self.stream = None
        self.rate = 48000
        self.channels = 2
        self.mix = "mix"
        self.file = None
        self.path: Path | None = None
        self.recording = False
        self.frames = 0
        self.engine_samples = 0
        self.resampler = None
        self.pending16 = np.zeros(0, dtype=np.float32)
        self.level_peak = None
        self.level_sum = None
        self.level_count = 0
        self.last_level = 0.0
        self.overflows = 0
        self.t0_monotonic: float | None = None
        self.running = True
        self.active = False

    def send(self, message: dict) -> None:
        with self.send_lock:
            try:
                self.control.send(message)
            except (BrokenPipeError, OSError):
                self.running = False

    def open(self, source: str, channels: str, sample_rate: int) -> None:
        import sounddevice as sd

        self.close()
        if source and source != "default":
            os.environ["PIPEWIRE_NODE"] = source
            device = "pipewire"
        else:
            os.environ.pop("PIPEWIRE_NODE", None)
            device = "default"
        info = sd.query_devices(device, "input")
        wanted = next((s["channels"] for s in pipewire_sources() if s["name"] == source), 2)
        self.channels = max(1, min(2, wanted, int(info["max_input_channels"])))
        self.rate = int(sample_rate or 48000)
        self.mix = channels
        self.stream = sd.InputStream(
            device=device,
            channels=self.channels,
            samplerate=self.rate,
            dtype="float32",
            blocksize=int(self.rate * 0.02),
            latency="low",
            callback=self._callback,
        )
        self.stream.start()
        self.active = True
        self._reset_engine_stream()
        self.send({"type": "opened", "source": source, "rate": self.rate, "channels": self.channels, "latency": self.stream.latency})

    def close(self) -> None:
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.active = False

    def _callback(self, indata, frames, time_info, status) -> None:
        if status.input_overflow:
            self.overflows += 1
        try:
            self.chunks.put_nowait((indata.copy(), time.monotonic()))
        except queue.Full:
            self.overflows += 1

    def _reset_engine_stream(self) -> None:
        import soxr

        self.resampler = soxr.ResampleStream(self.rate, ENGINE_RATE, 1, dtype="float32", quality="HQ")
        self.engine_samples = 0
        self.pending16 = np.zeros(0, dtype=np.float32)
        self._send_engine(("reset", 0))

    def _send_engine(self, message) -> bool:
        engine = self.engine
        if engine is None:
            return False
        try:
            engine.send(message)
            return True
        except (BrokenPipeError, OSError):
            self.engine = None
            return False

    def _accept(self) -> None:
        while self.running:
            try:
                connection = self.listener.accept()
            except OSError:
                return
            previous, self.engine = self.engine, connection
            if previous is not None:
                previous.close()
            self._send_engine(("reset", self.engine_samples))

    def start(self, path: str | None) -> None:
        import soundfile

        self.stop_recording(report=False)
        while not self.chunks.empty():
            try:
                self.chunks.get_nowait()
            except queue.Empty:
                break
        self.frames = 0
        self.t0_monotonic = None
        self._reset_engine_stream()
        if path:
            self.path = Path(path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.file = soundfile.SoundFile(self.path, "w", samplerate=self.rate, channels=self.channels, subtype="PCM_24", format="FLAC")
        else:
            self.path = None
            self.file = None
        self.recording = True
        self.send({"type": "started", "path": path, "rate": self.rate, "channels": self.channels})

    def stop_recording(self, report: bool = True) -> None:
        if not self.recording:
            return
        self.recording = False
        if self.file is not None:
            self.file.close()
            self.file = None
        if report:
            self.send({"type": "stopped", "path": str(self.path) if self.path else None, "duration": self.frames / self.rate, "t0_monotonic": self.t0_monotonic, "overflows": self.overflows})

    def _process(self) -> None:
        while self.running:
            try:
                data, arrived = self.chunks.get(timeout=0.2)
            except queue.Empty:
                continue
            frames = len(data)
            if self.recording:
                if self.t0_monotonic is None:
                    latency = self.stream.latency if self.stream is not None else 0.0
                    self.t0_monotonic = arrived - frames / self.rate - float(latency)
                    self.send({"type": "clock", "t0_monotonic": self.t0_monotonic})
                if self.file is not None:
                    self.file.write(data)
                self.frames += frames
            self._meter(data)
            self._feed_engine(data)

    def _meter(self, data: np.ndarray) -> None:
        peak = np.abs(data).max(axis=0)
        power = (data * data).sum(axis=0)
        if self.level_peak is None or len(self.level_peak) != len(peak):
            self.level_peak = peak
            self.level_sum = power
            self.level_count = len(data)
        else:
            self.level_peak = np.maximum(self.level_peak, peak)
            self.level_sum = self.level_sum + power
            self.level_count += len(data)
        now = time.monotonic()
        if now - self.last_level >= LEVEL_INTERVAL:
            rms = np.sqrt(self.level_sum / max(1, self.level_count))
            self.send({
                "type": "level",
                "peak": [round(20 * math.log10(float(p) + 1e-9), 1) for p in self.level_peak],
                "rms": [round(20 * math.log10(float(r) + 1e-9), 1) for r in rms],
                "clip": bool((self.level_peak >= 0.999).any()),
                "time": self.frames / self.rate if self.recording else None,
                "overflows": self.overflows,
            })
            self.level_peak = None
            self.last_level = now

    def _feed_engine(self, data: np.ndarray) -> None:
        if self.resampler is None:
            return
        if data.shape[1] == 1:
            mono = data[:, 0]
        elif self.mix == "left":
            mono = data[:, 0]
        elif self.mix == "right":
            mono = data[:, 1]
        else:
            mono = data.mean(axis=1)
        converted = self.resampler.resample_chunk(np.ascontiguousarray(mono, dtype=np.float32))
        self.pending16 = np.concatenate([self.pending16, converted])
        while len(self.pending16) >= ENGINE_CHUNK:
            chunk = self.pending16[:ENGINE_CHUNK]
            self.pending16 = self.pending16[ENGINE_CHUNK:]
            payload = (np.clip(chunk, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
            self._send_engine((self.engine_samples, payload))
            self.engine_samples += ENGINE_CHUNK

    def run(self) -> None:
        worker = threading.Thread(target=self._process, name="recorder", daemon=True)
        worker.start()
        threading.Thread(target=self._accept, name="accept", daemon=True).start()
        while self.running:
            if not self.control.poll(0.5):
                continue
            try:
                message = self.control.recv()
            except (EOFError, OSError):
                break
            kind = message.get("type")
            try:
                if kind == "open":
                    self.open(message.get("source", "default"), message.get("channels", "mix"), int(message.get("sample_rate") or 0))
                elif kind == "start":
                    self.start(message.get("path"))
                elif kind == "stop":
                    self.stop_recording()
                elif kind == "sources":
                    self.send({"type": "sources", "list": pipewire_sources()})
                elif kind == "quit":
                    break
            except Exception as error:
                self.send({"type": "error", "message": f"{type(error).__name__}: {error}"})
        self.stop_recording()
        self.close()
        self.running = False
        self.listener.close()


def recorder_main(control: Connection, address: str, authkey: bytes) -> None:
    try:
        Recorder(control, address, authkey).run()
    except KeyboardInterrupt:
        pass
    exit_quietly()
