from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

KEEP = 10


def new_path(directory: Path) -> Path:
    """A fresh engine log for this run of the app; only the most recent ones are kept."""
    old = sorted(directory.glob("engine-*.log"))
    for path in old[:max(0, len(old) - KEEP + 1)]:
        path.unlink(missing_ok=True)
    return directory / f"engine-{time.strftime('%Y%m%d-%H%M%S')}.log"


def log(message: str) -> None:
    print(f"[engine] {message}", file=sys.stderr, flush=True)


def _stamp() -> bytes:
    now = time.time()
    return f"{time.strftime('%H:%M:%S', time.localtime(now))}.{int(now * 1000) % 1000:03d} ".encode()


class OutputLog:
    """Copies everything the engine process prints into a log file, timestamped, and still shows it
    in the terminal. It works on the file descriptors, so the native libraries' own messages
    (CTranslate2, CUDA, PyTorch) land in the log too."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, "ab", buffering=0)
        self.stdout, self.terminal = os.dup(1), os.dup(2)
        read, write = os.pipe()
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(write, 1)
        os.dup2(write, 2)
        os.close(write)
        sys.stdout.reconfigure(line_buffering=True)
        self.thread = threading.Thread(target=self._pump, args=(read,), name="log", daemon=True)
        self.thread.start()

    def _pump(self, read: int) -> None:
        pending = b""
        while chunk := os.read(read, 65536):
            try:
                os.write(self.terminal, chunk)
            except OSError:
                pass
            *lines, pending = (pending + chunk).split(b"\n")
            for line in lines:
                self.file.write(_stamp() + line + b"\n")
        if pending:
            self.file.write(_stamp() + pending + b"\n")
        os.close(read)

    def close(self) -> None:
        """Puts the terminal back, which ends the pipe, and waits for the last lines to be written."""
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(self.stdout, 1)
        os.dup2(self.terminal, 2)
        self.thread.join(timeout=2)
        self.file.close()
