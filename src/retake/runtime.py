from __future__ import annotations

import multiprocessing
import os
import secrets
from multiprocessing.connection import Connection
from pathlib import Path

from . import paths
from .audio.recorder import recorder_main
from .engine import log
from .engine.process import engine_main


class Processes:
    def __init__(self):
        self.context = multiprocessing.get_context("spawn")
        self.authkey = secrets.token_bytes(16)
        self.address = str(paths.runtime_dir() / f"audio-{os.getpid()}.sock")
        self.recorder: multiprocessing.Process | None = None
        self.engine: multiprocessing.Process | None = None
        self.recorder_conn: Connection | None = None
        self.engine_conn: Connection | None = None
        self.engine_settings: dict | None = None
        self.engine_log: Path | None = None
        self._remove_stale_sockets()

    @staticmethod
    def _remove_stale_sockets() -> None:
        for path in paths.runtime_dir().glob("audio-*.sock"):
            pid = path.stem.removeprefix("audio-")
            if pid.isdigit() and not os.path.exists(f"/proc/{pid}"):
                path.unlink(missing_ok=True)

    def start_recorder(self) -> Connection:
        if os.path.exists(self.address):
            os.unlink(self.address)
        parent, child = self.context.Pipe()
        self.recorder = self.context.Process(target=recorder_main, args=(child, self.address, self.authkey), name="retake-recorder", daemon=True)
        self.recorder.start()
        child.close()
        self.recorder_conn = parent
        return parent

    def start_engine(self, settings: dict) -> Connection:
        self.stop_engine()
        self.engine_settings = settings
        if self.engine_log is None:
            self.engine_log = log.new_path(paths.logs_dir())
        parent, child = self.context.Pipe()
        self.engine = self.context.Process(target=engine_main, args=(child, self.address, self.authkey, {**settings, "log_file": str(self.engine_log)}),
                                           name="retake-engine", daemon=True)
        self.engine.start()
        child.close()
        self.engine_conn = parent
        return parent

    def stop_engine(self) -> None:
        if self.engine is not None and self.engine.is_alive():
            try:
                self.engine_conn.send({"type": "stop"})
            except (BrokenPipeError, OSError):
                pass
            self.engine.join(timeout=3)
            if self.engine.is_alive():
                self.engine.terminate()
        self.engine = None
        self.engine_conn = None

    def send_recorder(self, message: dict) -> None:
        if self.recorder_conn is not None:
            try:
                self.recorder_conn.send(message)
            except (BrokenPipeError, OSError):
                pass

    def send_engine(self, message: dict) -> None:
        if self.engine_conn is not None:
            try:
                self.engine_conn.send(message)
            except (BrokenPipeError, OSError):
                pass

    def pids(self) -> dict[str, int]:
        result = {"ui": os.getpid()}
        if self.recorder is not None and self.recorder.pid:
            result["recorder"] = self.recorder.pid
        if self.engine is not None and self.engine.pid:
            result["engine"] = self.engine.pid
        return result

    def shutdown(self) -> None:
        self.stop_engine()
        if self.recorder is not None and self.recorder.is_alive():
            self.send_recorder({"type": "quit"})
            self.recorder.join(timeout=3)
            if self.recorder.is_alive():
                self.recorder.terminate()
        if os.path.exists(self.address):
            os.unlink(self.address)
