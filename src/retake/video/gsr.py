from __future__ import annotations

import json
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path


def available() -> bool:
    return shutil.which("gpu-screen-recorder") is not None


def monitors() -> list[tuple[str, str]]:
    if not available():
        return []
    output = subprocess.run(["gpu-screen-recorder", "--list-monitors"], capture_output=True, text=True, timeout=10).stdout
    result = []
    for line in output.splitlines():
        name, _, size = line.partition("|")
        if name:
            result.append((name, size))
    return result


class ScreenRecorder:
    def __init__(self, output: Path, capture: str, audio_source: str | None, fps: int, socket_path: Path, log_path: Path | None = None):
        self.output = output
        self.capture = capture
        self.audio_source = audio_source
        self.fps = fps
        self.socket_path = socket_path
        self.log_path = log_path
        self.process: subprocess.Popen | None = None
        self._ids = 0

    def command(self) -> list[str]:
        command = ["gpu-screen-recorder"]
        kind, _, value = self.capture.partition(":")
        if kind == "region":
            command += ["-w", "region", "-region", value]
        elif kind == "monitor":
            command += ["-w", value]
        elif kind in ("portal", "focused", "screen"):
            command += ["-w", kind]
        else:
            command += ["-w", self.capture or "screen"]
        command += [
            "-f", str(self.fps), "-k", "auto", "-fm", "cfr", "-fallback-cpu-encoding", "yes",
            "-write-first-frame-ts", "yes", "-ipc", str(self.socket_path), "-c", "mp4", "-o", str(self.output),
        ]
        if self.audio_source:
            source = self.audio_source if self.audio_source.startswith(("default_", "device:", "app:")) else f"device:{self.audio_source}"
            command += ["-a", source]
        return command

    def start(self) -> None:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        log = open(self.log_path, "ab") if self.log_path else subprocess.DEVNULL
        self.process = subprocess.Popen(self.command(), stdout=log, stderr=log, start_new_session=True)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not self.socket_path.exists():
            if self.process.poll() is not None:
                raise RuntimeError(f"gpu-screen-recorder exited with {self.process.returncode}")
            time.sleep(0.05)

    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def request(self, name: str, data=None, timeout: float = 30.0) -> dict:
        self._ids += 1
        payload = {"id": self._ids, "name": name}
        if data is not None:
            payload["data"] = data
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(str(self.socket_path))
            client.sendall((json.dumps(payload) + "\n").encode())
            buffer = b""
            while not buffer.endswith(b"\n"):
                chunk = client.recv(4096)
                if not chunk:
                    break
                buffer += chunk
        return json.loads(buffer.decode() or "{}")

    def set_paused(self, paused: bool) -> None:
        if not self.alive():
            return
        try:
            self.request("set-paused", paused, timeout=5)
        except OSError:
            self.process.send_signal(signal.SIGUSR2)

    def stop(self) -> Path | None:
        if not self.alive():
            return self.output if self.output.exists() else None
        path = None
        try:
            reply = self.request("stop")
            if reply.get("result") == "ok" and reply.get("data"):
                path = Path(reply["data"])
        except OSError:
            self.process.send_signal(signal.SIGINT)
        try:
            self.process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.process.kill()
        return path or (self.output if self.output.exists() else None)
