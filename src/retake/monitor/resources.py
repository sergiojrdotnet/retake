from __future__ import annotations

import csv
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

VRAM_WARN = 0.92
RAM_WARN_MB = 1024
DISK_WARN_MINUTES = 10


@dataclass
class GpuProcess:
    pid: int
    name: str
    memory_mb: float


@dataclass
class GpuStats:
    name: str = ""
    utilization: float | None = None
    encoder: float | None = None
    memory_used_mb: float | None = None
    memory_total_mb: float | None = None
    temperature: float | None = None
    throttled: list[str] = field(default_factory=list)
    processes: list[GpuProcess] = field(default_factory=list)
    source: str = "none"


@dataclass
class Snapshot:
    time: float
    cpu: float
    ram_used_mb: float
    ram_total_mb: float
    ram_available_mb: float
    disk_free_gb: float
    disk_write_mbps: float
    gpu: GpuStats
    processes: dict[str, dict]
    warnings: list[str]

    def summary(self) -> dict:
        gpu = self.gpu
        return {
            "cpu": round(self.cpu),
            "ram": f"{self.ram_used_mb / 1024:.1f}/{self.ram_total_mb / 1024:.0f} GB",
            "gpu": None if gpu.utilization is None else round(gpu.utilization),
            "vram": None if gpu.memory_used_mb is None else f"{gpu.memory_used_mb / 1024:.1f}/{gpu.memory_total_mb / 1024:.1f} GB",
            "warnings": self.warnings,
        }


class Nvml:
    def __init__(self):
        self.handle = None
        self.module = None
        try:
            import pynvml

            pynvml.nvmlInit()
            if pynvml.nvmlDeviceGetCount() > 0:
                self.module = pynvml
                self.handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception:
            self.module = None

    @property
    def ok(self) -> bool:
        return self.handle is not None

    def read(self) -> GpuStats:
        nv = self.module
        stats = GpuStats(source="nvml")
        try:
            name = nv.nvmlDeviceGetName(self.handle)
            stats.name = name.decode() if isinstance(name, bytes) else name
            rates = nv.nvmlDeviceGetUtilizationRates(self.handle)
            stats.utilization = float(rates.gpu)
            memory = nv.nvmlDeviceGetMemoryInfo(self.handle)
            stats.memory_used_mb = memory.used / 2**20
            stats.memory_total_mb = memory.total / 2**20
            stats.temperature = float(nv.nvmlDeviceGetTemperature(self.handle, nv.NVML_TEMPERATURE_GPU))
            stats.encoder = float(nv.nvmlDeviceGetEncoderUtilization(self.handle)[0])
            reasons = nv.nvmlDeviceGetCurrentClocksThrottleReasons(self.handle)
            if reasons & getattr(nv, "nvmlClocksThrottleReasonSwThermalSlowdown", 0x20) or reasons & getattr(nv, "nvmlClocksThrottleReasonHwThermalSlowdown", 0x40):
                stats.throttled.append("thermal")
            if reasons & getattr(nv, "nvmlClocksThrottleReasonSwPowerCap", 0x4):
                stats.throttled.append("power")
            seen: dict[int, GpuProcess] = {}
            for getter in (nv.nvmlDeviceGetComputeRunningProcesses, nv.nvmlDeviceGetGraphicsRunningProcesses):
                for proc in getter(self.handle):
                    used = (proc.usedGpuMemory or 0) / 2**20
                    if proc.pid in seen:
                        seen[proc.pid].memory_mb = max(seen[proc.pid].memory_mb, used)
                        continue
                    try:
                        name = psutil.Process(proc.pid).name()
                    except psutil.Error:
                        name = str(proc.pid)
                    seen[proc.pid] = GpuProcess(proc.pid, name, used)
            stats.processes = sorted(seen.values(), key=lambda p: -p.memory_mb)
        except Exception:
            pass
        return stats


def _amd() -> GpuStats | None:
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]")):
        busy = card / "device/gpu_busy_percent"
        if busy.exists():
            stats = GpuStats(source="amdgpu")
            try:
                stats.utilization = float(busy.read_text())
                used = card / "device/mem_info_vram_used"
                total = card / "device/mem_info_vram_total"
                if used.exists() and total.exists():
                    stats.memory_used_mb = int(used.read_text()) / 2**20
                    stats.memory_total_mb = int(total.read_text()) / 2**20
            except (OSError, ValueError):
                pass
            return stats
    return None


class ResourceMonitor:
    def __init__(self, disk_path: Path):
        self.disk_path = disk_path
        self.nvml = Nvml()
        self.watched: dict[str, int] = {}
        self._processes: dict[int, psutil.Process] = {}
        self._last_written: dict[Path, tuple[float, int]] = {}
        self.recording_files: list[Path] = []
        self.bitrate_mbps = 2.5
        self.engine_metrics: dict = {}
        psutil.cpu_percent(None)

    def watch(self, pids: dict[str, int]) -> None:
        self.watched = dict(pids)

    def gpu(self) -> GpuStats:
        if self.nvml.ok:
            return self.nvml.read()
        return _amd() or GpuStats()

    def _process(self, pid: int) -> psutil.Process | None:
        process = self._processes.get(pid)
        if process is None:
            try:
                process = psutil.Process(pid)
                process.cpu_percent(None)
                self._processes[pid] = process
            except psutil.Error:
                return None
        return process

    def _write_rate(self) -> float:
        total = 0.0
        now = time.monotonic()
        for path in self.recording_files:
            try:
                size = path.stat().st_size
            except OSError:
                continue
            previous = self._last_written.get(path)
            self._last_written[path] = (now, size)
            if previous and now > previous[0]:
                total += (size - previous[1]) / (now - previous[0]) / 2**20
        return max(0.0, total)

    def sample(self) -> Snapshot:
        memory = psutil.virtual_memory()
        try:
            usage = shutil.disk_usage(self.disk_path if self.disk_path.exists() else Path.home())
            free_gb = usage.free / 2**30
        except OSError:
            free_gb = 0.0
        gpu = self.gpu()
        processes = {}
        gpu_memory = {p.pid: p.memory_mb for p in gpu.processes}
        for role, pid in self.watched.items():
            process = self._process(pid)
            if process is None:
                continue
            try:
                processes[role] = {
                    "pid": pid,
                    "cpu": process.cpu_percent(None),
                    "rss_mb": process.memory_info().rss / 2**20,
                    "vram_mb": gpu_memory.get(pid, 0.0),
                }
            except psutil.Error:
                continue
        write_rate = self._write_rate()
        warnings = []
        if gpu.memory_used_mb and gpu.memory_total_mb and gpu.memory_used_mb / gpu.memory_total_mb > VRAM_WARN:
            holders = ", ".join(f"{p.name} {p.memory_mb / 1024:.1f} GB" for p in gpu.processes[:3])
            warnings.append(f"VRAM almost full ({holders})")
        if memory.available / 2**20 < RAM_WARN_MB:
            warnings.append("RAM almost full")
        minutes_left = free_gb * 1024 / max(self.bitrate_mbps / 8, 0.01) / 60
        if minutes_left < DISK_WARN_MINUTES:
            warnings.append(f"Disk space for about {minutes_left:.0f} min")
        if gpu.throttled:
            warnings.append("GPU throttling: " + ", ".join(gpu.throttled))
        lag = self.engine_metrics.get("latency", {}).get("tracking")
        if lag is not None and lag > 1.2:
            warnings.append(f"Tracking is {lag:.1f}s behind")
        return Snapshot(
            time=time.time(),
            cpu=psutil.cpu_percent(None),
            ram_used_mb=(memory.total - memory.available) / 2**20,
            ram_total_mb=memory.total / 2**20,
            ram_available_mb=memory.available / 2**20,
            disk_free_gb=free_gb,
            disk_write_mbps=write_rate,
            gpu=gpu,
            processes=processes,
            warnings=warnings,
        )

    def disk_minutes(self, snapshot: Snapshot) -> float:
        return snapshot.disk_free_gb * 1024 / max(self.bitrate_mbps / 8, 0.01) / 60


def estimate_preset(settings: dict) -> tuple[float, float]:
    from ..engine import models

    vram = ram = 0.0
    on_gpu = settings.get("device") == "cuda"
    if settings.get("tracking") == "whisper":
        spec = models.REGISTRY.get(f"whisper-{settings.get('whisper_model', 'small.en')}")
        if spec:
            vram += spec.vram_mb if on_gpu else 0
            ram += spec.ram_mb
    else:
        ram += 900
    if settings.get("commands"):
        ram += 300
    if settings.get("scorer") == "wav2vec2":
        spec = models.get("wav2vec2-espeak-cv")
        vram += spec.vram_mb if on_gpu else 0
        ram += spec.ram_mb if not on_gpu else 400
    if settings.get("vad") == "silero":
        ram += 250
    return vram, ram


class ResourceLog:
    FIELDS = ["time", "cpu", "ram_mb", "gpu", "vram_mb", "encoder", "disk_write_mbps", "tracking_lag", "scorer_s"]

    def __init__(self, path: Path):
        self.path = path
        self.handle = open(path, "a", newline="")
        self.writer = csv.writer(self.handle)
        if path.stat().st_size == 0:
            self.writer.writerow(self.FIELDS)

    def write(self, session_time: float, snapshot: Snapshot, metrics: dict) -> None:
        latency = metrics.get("latency", {})
        gpu = snapshot.gpu
        self.writer.writerow([
            f"{session_time:.2f}", f"{snapshot.cpu:.0f}", f"{snapshot.ram_used_mb:.0f}",
            "" if gpu.utilization is None else f"{gpu.utilization:.0f}",
            "" if gpu.memory_used_mb is None else f"{gpu.memory_used_mb:.0f}",
            "" if gpu.encoder is None else f"{gpu.encoder:.0f}",
            f"{snapshot.disk_write_mbps:.2f}",
            f"{latency.get('tracking', 0):.2f}", f"{latency.get('scorer', 0):.2f}",
        ])
        self.handle.flush()

    def close(self) -> None:
        self.handle.close()
