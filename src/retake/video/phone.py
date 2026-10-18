from __future__ import annotations

import os
import pty
import re
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULTS = {
    "camera": "back",
    "size": "3840x2160",
    "fps": 30,
    "codec": "h265",
    "bitrate": "40M",
    "container": "mkv",
    "shape": "landscape",
    "flip": False,
    "preview": False,
    "serial": "",
}

LOOPBACK_LABEL = "Retake phone"
SETUP = (
    "sudo pacman -S v4l2loopback-dkms\n"
    "echo v4l2loopback | sudo tee /etc/modules-load.d/v4l2loopback.conf\n"
    "echo 'options v4l2loopback video_nr=42 card_label=\"Retake phone\"' | sudo tee /etc/modprobe.d/v4l2loopback.conf\n"
    "sudo modprobe v4l2loopback"
)


def loopback_device() -> str | None:
    """The virtual camera scrcpy feeds for the live preview: ours by label, else any v4l2loopback device."""
    fallback = None
    for entry in sorted(Path("/sys/class/video4linux").glob("video*")):
        try:
            name = (entry / "name").read_text().strip()
        except OSError:
            continue
        if name == LOOPBACK_LABEL:
            return f"/dev/{entry.name}"
        if fallback is None and ("loopback" in name.lower() or name.startswith("Dummy video device")):
            fallback = f"/dev/{entry.name}"
    return fallback


def loopback_fed(device: str) -> bool:
    """Whether a producer is streaming into the virtual camera, at its own picture size by now.

    scrcpy announces its sink before it sets that size; a reader opening in between pins the
    previous size and blocks scrcpy for good. v4l2loopback reports "capture" once it's safe."""
    try:
        return (Path("/sys/class/video4linux") / Path(device).name / "state").read_text().strip() == "capture"
    except OSError:
        return True


def available() -> bool:
    return shutil.which("scrcpy") is not None


@dataclass
class Phone:
    serial: str
    state: str
    model: str


def phones() -> list[Phone]:
    """Android devices adb can see, with their state: device, unauthorized or offline."""
    adb = shutil.which("adb")
    if adb is None:
        return []
    try:
        output = subprocess.run([adb, "devices", "-l"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    found = []
    for line in output.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 2:
            continue
        model = next((f.split(":", 1)[1] for f in fields[2:] if f.startswith("model:")), "")
        found.append(Phone(fields[0], fields[1], model.replace("_", " ")))
    return found


@dataclass
class Camera:
    id: str
    facing: str
    size: str
    fps: list[int]
    sizes: list[str]
    high_speed: list[tuple[str, list[int]]]

    def as_dict(self) -> dict:
        return {"id": self.id, "facing": self.facing, "size": self.size, "fps": self.fps, "sizes": self.sizes,
                "high_speed": [{"size": size, "fps": fps} for size, fps in self.high_speed]}

    @classmethod
    def from_dict(cls, data: dict) -> Camera:
        return cls(data["id"], data["facing"], data["size"], list(data["fps"]), list(data["sizes"]),
                   [(entry["size"], list(entry["fps"])) for entry in data.get("high_speed", [])])


_CAMERA_LINE = re.compile(r"--camera-id=(\S+)\s+\((\w+), (\d+x\d+), fps=\{([^}]*)\}")
_HIGH_SPEED_SIZE = re.compile(r"^\s+- (\d+x\d+) \(fps=\{([^}]*)\}\)")
_SIZE = re.compile(r"^\s+- (\d+x\d+)\s*$")


def _numbers(text: str) -> list[int]:
    return [int(value) for value in re.findall(r"\d+", text)]


def parse_cameras(output: str) -> list[Camera]:
    """Reads `scrcpy --list-camera-sizes`: each camera, its sizes and frame rates, and high-speed modes."""
    cameras: list[Camera] = []
    high_speed = False
    for line in output.splitlines():
        if match := _CAMERA_LINE.search(line):
            cameras.append(Camera(match.group(1), match.group(2), match.group(3), _numbers(match.group(4)), [], []))
            high_speed = False
        elif not cameras:
            continue
        elif "High speed capture" in line:
            high_speed = True
        elif high_speed and (match := _HIGH_SPEED_SIZE.match(line)):
            cameras[-1].high_speed.append((match.group(1), _numbers(match.group(2))))
        elif not high_speed and (match := _SIZE.match(line)):
            cameras[-1].sizes.append(match.group(1))
    return cameras


def device_name(output: str) -> str:
    """'Xiaomi POCO 2412DPC0AG' from scrcpy's '[server] INFO: Device: [Xiaomi] POCO 2412DPC0AG (Android 16)'."""
    match = re.search(r"Device: \[([^\]]*)\] (.+?) \(Android", output)
    return f"{match.group(1)} {match.group(2)}".strip() if match else ""


def detect_cameras(serial: str = "") -> tuple[list[Camera], str]:
    args = ["scrcpy", "--list-camera-sizes"] + ([f"--serial={serial}"] if serial else [])
    try:
        output = subprocess.run(args, capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return [], ""
    return parse_cameras(output), device_name(output)


def _pixels(size: str) -> int:
    width, height = (int(v) for v in size.split("x"))
    return width * height


def _ratio(size: str) -> str:
    width, height = (int(v) for v in size.split("x"))
    for name, value in (("16:9", 16 / 9), ("4:3", 4 / 3), ("1:1", 1.0), ("21:9", 21 / 9)):
        if abs(width / height - value) < 0.02:
            return name
    return f"{width}:{height}"


def video_sizes(camera: Camera) -> list[str]:
    """The sizes worth offering for video: the common 16:9 ones the camera has, then its full sensor."""
    wanted = ["3840x2160", "2560x1440", "1920x1080", "1280x720"]
    chosen = [size for size in wanted if size in camera.sizes]
    largest = max(camera.sizes, key=_pixels, default=camera.size)
    if largest not in chosen:
        chosen.append(largest)
    return chosen


def describe_size(size: str) -> str:
    return f"{size.replace('x', ' × ')} ({_ratio(size)})"


def find_camera(cameras: list[Camera], choice: str) -> Camera | None:
    if not cameras:
        return None
    if choice.isdigit():
        return next((c for c in cameras if c.id == choice), None)
    return next((c for c in cameras if c.facing == choice), None)


def resolve(settings: dict, cameras: list[Camera]) -> tuple[dict, str]:
    """Fits the saved settings to what the phone's camera supports; returns them and a note when changed."""
    options = {**DEFAULTS, **{k: v for k, v in settings.items() if k in DEFAULTS and v not in (None, "")}}
    camera = find_camera(cameras, str(options["camera"]))
    if camera is None:
        return options, ""
    notes = []
    fps = int(options["fps"])
    size = options["size"] or max(camera.sizes, key=_pixels, default=camera.size)
    high = [(s, f) for s, f in camera.high_speed if fps in f]
    if fps not in camera.fps and high:
        fitting = [s for s, _ in high if _pixels(s) <= _pixels(size)] or [s for s, _ in high]
        options["size"] = max(fitting, key=_pixels)
        options["high_speed"] = True
        if options["size"] != size:
            notes.append(f"{fps} fps is a high-speed mode, recorded at {options['size'].replace('x', '×')}")
    elif fps not in camera.fps:
        best = max((f for f in camera.fps if f <= fps), default=max(camera.fps, default=30))
        notes.append(f"this camera doesn't do {fps} fps; recording at {best}")
        options["fps"] = best
    if not options.get("high_speed") and camera.sizes and size not in camera.sizes:
        smaller = [s for s in camera.sizes if _pixels(s) <= _pixels(size)] or camera.sizes
        same_shape = [s for s in smaller if _ratio(s) == _ratio(size)]
        fallback = max(same_shape or smaller, key=_pixels)
        notes.append(f"this camera has no {size.replace('x', '×')}; recording at {fallback.replace('x', '×')}")
        options["size"] = fallback
    options["camera"] = camera.id
    options["facing"] = camera.facing
    return options, "; ".join(notes)


def capture_rotation(options: dict) -> int:
    """scrcpy delivers the camera upright for a phone held sideways. Held upright, the picture
    has to turn a quarter: clockwise for the back camera, the other way for the front one."""
    rotation = 0
    if options.get("shape") == "portrait":
        rotation = 270 if options.get("facing", options.get("camera")) == "front" else 90
    if options.get("flip"):
        rotation += 180
    return rotation % 360


def portrait(settings: dict) -> bool:
    return settings.get("shape", DEFAULTS["shape"]) == "portrait"


def aspect(size: str) -> str:
    """The preview keeps the recording's shape; sensors are often 4:3 while video is 16:9."""
    try:
        width, height = (int(v) for v in size.lower().split("x"))
        return f"{width}:{height}"
    except ValueError:
        return "sensor"


def command(output: Path | None, settings: dict, sink: str | None = None) -> list[str]:
    """scrcpy arguments: recording to output, feeding the virtual camera sink, or both.

    Without output it's a preview: a smaller picture and no audio, only for the camera panel."""
    options = {**DEFAULTS, **{k: v for k, v in settings.items() if k in DEFAULTS and v not in (None, "")}}
    options.update({k: settings[k] for k in ("high_speed", "facing") if k in settings})
    camera = str(options["camera"])
    args = ["scrcpy", "--video-source=camera", "--no-control"]
    args.append(f"--camera-id={camera}" if camera.isdigit() else f"--camera-facing={camera}")
    if output is None:
        args += ["--max-size=1280", "--no-audio", f"--camera-ar={aspect(options['size'])}"]
    elif options["size"]:
        args.append(f"--camera-size={options['size']}")
    if output is not None and options.get("high_speed"):
        args.append("--camera-high-speed")
    preview_fps = min(int(options["fps"]), 30) if output is None and options.get("high_speed") else int(options["fps"])
    args += [f"--camera-fps={preview_fps}", f"--video-codec={options['codec']}"]
    if output is not None:
        args += [
            f"--record={output}", f"--record-format={output.suffix.lstrip('.')}", f"--video-bit-rate={options['bitrate']}",
            # A keyframe every second lets the waiting and pauses be cut out later without re-encoding.
            "--video-codec-options=i-frame-interval:int=1",
            # The phone microphone is recorded only to line the video up with Retake's own audio, and
            # never played: through the laptop speakers it would feed back into the microphones.
            "--audio-source=mic", "--audio-codec=aac", "--no-audio-playback",
        ]
    rotation = capture_rotation(options)
    if rotation:
        args.append(f"--capture-orientation={rotation}")
    if sink:
        args += [f"--v4l2-sink={sink}", "--no-window"]
    elif output is not None and options["preview"]:
        args += ["--window-title=Retake phone camera", "--window-width=480", "--window-height=270"]
    else:
        args.append("--no-window")
    if options["serial"]:
        args.append(f"--serial={options['serial']}")
    return args


class PhoneRecorder:
    """Runs scrcpy on an Android phone's camera: recording one part to a file, feeding the
    virtual camera for the live preview, or both at once."""

    def __init__(self, output: Path | None, settings: dict, log: Path, sink: str | None = None):
        self.output = output
        self.settings = settings
        self.log = log
        self.sink = sink
        self.process: subprocess.Popen | None = None
        self.started: float | None = None
        self.error = ""
        self._ready = threading.Event()

    def start(self, timeout: float = 20.0) -> None:
        """Returns once scrcpy is recording, or, for a preview, once it has opened the virtual camera.

        Nothing may read the virtual camera before then: scrcpy sets the picture size when it opens
        the device with its first frame, and a reader that got there first pins the previous size."""
        if self.output is not None:
            self.output.parent.mkdir(parents=True, exist_ok=True)
        self.log.parent.mkdir(parents=True, exist_ok=True)
        args = command(self.output, self.settings, self.sink)
        # scrcpy holds its log lines back when writing to a pipe; a pseudo-terminal gets each line as it happens.
        master, slave = pty.openpty()
        self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=slave, stderr=slave, close_fds=True)
        os.close(slave)
        threading.Thread(target=self._read, args=(master,), daemon=True).start()
        if not self._ready.wait(timeout):
            self.stop()
            raise RuntimeError(self.error or "the phone camera did not start in time (is the phone unlocked?)")
        if self.started is None:
            raise RuntimeError(self.error or "scrcpy stopped before the camera started")

    def _read(self, master: int) -> None:
        with open(self.log, "w", encoding="utf-8") as log, os.fdopen(master, "r", encoding="utf-8", errors="replace") as output:
            for line in self._lines(output):
                log.write(line)
                log.flush()
                text = line.strip()
                if "Recording started" in text or (self.output is None and "v4l2" in text.lower() and "ERROR" not in text):
                    self.started = time.monotonic()
                    self._ready.set()
                elif "number of open cameras" in text or "Camera device in use" in text or "CAMERA_IN_USE" in text:
                    # Android lets one app use the camera; scrcpy's own errors that follow ("Demuxer error") say less.
                    self.error = "the phone's camera is in use by another app; close the Camera app on the phone"
                elif text.startswith("ERROR") and not self.error.startswith("the phone's camera"):
                    self.error = text.removeprefix("ERROR:").strip()
        self._ready.set()

    @staticmethod
    def _lines(output):
        try:
            yield from output
        except OSError:
            # Reading the terminal fails with EIO once scrcpy exits; that's the end of its output.
            return

    def stop(self, timeout: float = 15.0) -> Path | None:
        if self.process is None:
            return None
        if self.process.poll() is None:
            # Like Ctrl+C in a terminal: scrcpy finishes writing the recording before it exits.
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(5)
        if self.output is None:
            return None
        return self.output if self.output.exists() and self.output.stat().st_size > 0 else None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None
