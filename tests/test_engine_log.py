import subprocess
import sys
import textwrap
import time

from retake.engine import log
from retake.engine.process import Worker


def test_new_path_keeps_only_recent_logs(tmp_path):
    for index in range(12):
        (tmp_path / f"engine-20260101-0000{index:02d}.log").write_text("")
    path = log.new_path(tmp_path)
    assert path.parent == tmp_path and path.name.startswith("engine-")
    remaining = sorted(p.name for p in tmp_path.glob("engine-*.log"))
    assert len(remaining) == log.KEEP - 1
    assert remaining[0] == "engine-20260101-000003.log"


def test_output_log_captures_python_and_native_output(tmp_path):
    target = tmp_path / "engine.log"
    script = textwrap.dedent(f"""
        import os, sys
        from pathlib import Path
        from retake.engine.log import OutputLog, log
        output = OutputLog(Path({str(target)!r}))
        print("from print")
        log("model ready")
        os.write(2, b"from a native library\\n")
        output.close()
        print("after close")
    """)
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    lines = target.read_text().splitlines()
    assert [line.split(" ", 1)[1] for line in lines] == ["from print", "[engine] model ready", "from a native library"]
    assert "from print" in result.stdout + result.stderr and "after close" in result.stdout


def test_scoring_does_not_wait_for_tracking():
    tracking, scoring = Worker("tracking"), Worker("scoring")
    done = []
    tracking.submit(lambda: time.sleep(0.5))
    started = time.monotonic()
    scoring.submit(lambda: done.append(time.monotonic() - started))
    deadline = time.monotonic() + 2
    while not done and time.monotonic() < deadline:
        time.sleep(0.01)
    tracking.stop()
    scoring.stop()
    assert done and done[0] < 0.3
