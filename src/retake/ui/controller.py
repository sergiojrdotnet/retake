from __future__ import annotations

import os
import threading
import time
import traceback
from pathlib import Path

import numpy as np
from PySide6.QtCore import Property, QCoreApplication, QObject, QSocketNotifier, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QMediaDevices, QVideoFrameFormat, QVideoSink
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .. import config as config_module
from .. import paths
from .. import project as projects
from ..engine import models as model_registry
from ..engine import settings as engine_settings
from ..languages import packs
from ..monitor.resources import ResourceLog, ResourceMonitor, estimate_preset
from ..phonetics import guides as guide_module
from ..project import Item, Project
from ..runtime import Processes
from ..script import parser
from ..script.lexicon import Lexicon
from ..script.model import ADLIB, WORD, Script
from ..session import preflight
from ..session import takes as kinds
from ..session.coach import CoachSettings, PracticeHistory
from ..session.session import Session, SessionSettings
from ..session.takes import COMPLETE, TakeLog
from ..video import phone as phone_video
from . import modeljobs, portal
from .sounds import SoundCues, cue_for_notice, cue_for_state
from .editor import EditorController
from .models import DictListModel
from .phonepreview import PhonePreview
from .playback import Player

# What each layout of the recording page shows; Tab cycles them in this order.
LAYOUTS = {
    "full": {"prompter": True, "camera": True, "takes": True, "coach": True},
    "focus": {"prompter": True},
    "lens": {"strip": True},
}
LAYOUT_ORDER = list(LAYOUTS)
DISPLAY_MODES = ["scroll", "step", "card", "page"]


class Controller(QObject):
    pageChanged = Signal()
    stateChanged = Signal()
    scriptChanged = Signal()
    positionChanged = Signal()
    levelChanged = Signal()
    timeChanged = Signal()
    engineChanged = Signal()
    resourcesChanged = Signal()
    settingsChanged = Signal()
    layoutChanged = Signal()
    coachChanged = Signal()
    drillChanged = Signal()
    uncoachedChanged = Signal()
    devicesChanged = Signal()
    preflightChanged = Signal()
    recentChanged = Signal()
    notice = Signal(str, str)
    cameraRecord = Signal(str)
    cameraStop = Signal()
    enginePendingChanged = Signal()
    raiseWindow = Signal()
    _ttsDone = Signal(float, float, str)
    _finalized = Signal("QVariant")
    projectChanged = Signal()
    itemChanged = Signal()
    explorerChanged = Signal()
    seekEditor = Signal(float)
    projectLocationChosen = Signal(str)
    phoneFeedChanged = Signal()
    phonePreviewChanged = Signal()
    phoneCamerasChanged = Signal()
    _phoneCamerasFound = Signal("QVariant")
    _phoneUpdate = Signal()
    _finishStep = Signal(str)
    finishingChanged = Signal()
    startingVideoChanged = Signal()
    _videoStarted = Signal(bool)
    openingChanged = Signal()
    _synced = Signal()
    _portalResult = Signal(str, "QVariant")
    _downloadProgress = Signal(str, float, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = config_module.load()
        self.processes = Processes()
        self.player = Player()
        self._page = "start"
        self._state = "idle"
        self.cues = SoundCues(self.config, self)
        self._recording = False
        self._rehearsal = False
        self._time = 0.0
        self._level = {"peak": [-90.0], "rms": [-90.0], "clip": False}
        self._engines: dict = {}
        self._resources: dict = {}
        self._current_sentence = 0
        self._current_word = -1
        self._coach: dict = {}
        self._preflight: list[dict] = []
        self._sources: list[dict] = []
        self._review: dict = {}
        self._engine_metrics: dict = {}
        self._layout = self._layout_named(self.config["general"].get("layout"))
        self._panels = dict(LAYOUTS[self._layout])
        self._display_mode = self.config["prompter"].get("mode", "scroll")
        self.script: Script | None = None
        self.script_path: Path | None = None
        self.lexicon = Lexicon(None)
        self.guides = guide_module.GuideBook()
        self.history = PracticeHistory.load(paths.data_dir() / "practice.json")
        self.paragraphs = DictListModel(["paragraph", "section", "sectionLevel", "kind", "note", "sentences"], self)
        self.takes = DictListModel(["id", "sentence", "number", "status", "reason", "start", "end", "score", "flagged", "text"], self)
        self.models = DictListModel(["id", "title", "role", "license", "size", "installed", "progress", "note", "available"], self)
        self.model_jobs = DictListModel(["job", "jobTitle", "jobHint", "uses", "value", "title", "detail", "model", "installed", "available", "builtin", "selected", "progress"], self)
        self._download_progress: dict[str, float] = {}
        self._engine_pending = False
        self._finishing = ""
        self._drill: dict = {}
        self._word_marks: dict = {}
        self._starting_video = ""
        self._opening = ""
        self._window = None
        self._pending_open: tuple | None = None
        self._awaiting_sync = False
        self._open_timer = QTimer(self, singleShot=True, interval=250)
        self._open_timer.timeout.connect(self._run_pending_open)
        self._synced.connect(self._run_pending_open)
        self.editor = EditorController(self)
        self.session: Session | None = None
        self.log: TakeLog | None = None
        self.project: Project | None = None
        self.item: Item | None = None
        self.part_index = 0
        self.part_audio: Path | None = None
        self._pickup: list[int] = []
        self._expanded: set[str] = set()
        self._explorer_visible = bool(self.config["general"].get("explorer", True))
        self._script_meta: dict[str, tuple[float, str, int]] = {}
        self.explorer = DictListModel(["kind", "depth", "id", "part", "title", "detail", "expanded", "expandable", "current"], self)
        self.phone: phone_video.PhoneRecorder | None = None
        self.phone_preview: phone_video.PhoneRecorder | None = None
        self.phone_frames = PhonePreview(self)
        self._known_phones: dict[str, dict] = self._load_known_phones()
        self._settings_cache: dict | None = None
        self.settingsChanged.connect(self._forget_settings)
        # Changing the edit rules can make the automatic cut differ from the current one.
        self.settingsChanged.connect(self.editor.resetChanged)
        self._active_serial = ""
        self._detecting = False
        self.phone_frames.activeChanged.connect(self.phonePreviewChanged)
        self._phone_lock = threading.Lock()
        self._media_devices = QMediaDevices(self)
        self._media_devices.videoInputsChanged.connect(self.devicesChanged)
        self.resource_log: ResourceLog | None = None
        self.camera_file: Path | None = None
        self.camera_started: float | None = None
        self.camera_finished = False
        self.audio_t0: float | None = None
        self._recorder_stopped: dict | None = None
        self._last_tick = 0.0
        self._closing = False
        self._engine_crashes: list[float] = []
        self.monitor = ResourceMonitor(Path(self.config["general"]["projects_dir"]))
        self._ttsDone.connect(self._on_tts_done)
        self._finalized.connect(self._on_finalized)
        self._finishStep.connect(self._set_finishing)
        self._videoStarted.connect(self._go_live)
        self._video_timer = QTimer(self, singleShot=True, interval=25000)
        self._video_timer.timeout.connect(self._video_timed_out)
        self._phoneUpdate.connect(self._update_phone_preview)
        self.phoneFeedChanged.connect(self._restart_phone_frames)
        self._phoneCamerasFound.connect(self._set_phone_cameras)
        self._portalResult.connect(self._on_portal)
        self._downloadProgress.connect(self._on_download_progress)
        self._start_processes()
        self._start_control_server()
        self._resource_timer = QTimer(self, interval=1000, timeout=self._sample_resources)
        self._resource_timer.start()
        self._refresh_models()
        self.processes.send_recorder({"type": "sources"})
        self.pedal = None
        self._start_pedal()
        self._watcher = None

    def _start_processes(self) -> None:
        self.recorder_conn = self.processes.start_recorder()
        self.recorder_notifier = QSocketNotifier(self.recorder_conn.fileno(), QSocketNotifier.Read, self)
        self.recorder_notifier.activated.connect(self._read_recorder)
        audio = self.config["audio"]
        self.processes.send_recorder({"type": "open", "source": audio.get("input", "default"), "channels": audio.get("channels", "mix"), "sample_rate": audio.get("sample_rate", 0)})
        self._start_engine()

    def _start_engine(self) -> None:
        previous = getattr(self, "engine_notifier", None)
        if previous is not None:
            previous.setEnabled(False)
            previous.deleteLater()
            self.engine_notifier = None
        settings = engine_settings.build(self.config)
        self._engines = {}
        self.engineChanged.emit()
        self.engine_conn = self.processes.start_engine(settings)
        self.engine_notifier = QSocketNotifier(self.engine_conn.fileno(), QSocketNotifier.Read, self)
        self.engine_notifier.activated.connect(self._read_engine)
        self._engine_settings = settings
        self._update_listening()

    def _update_listening(self) -> None:
        """Everything is listened to while recording; between recordings on the Record page, only voice
        commands, so "retake, start recording" works."""
        idle = self._page == "session" and not self._recording and not self._starting_video and not self._finishing
        self.processes.send_engine({"type": "listen", "active": self._recording, "commands": idle})

    def _start_control_server(self) -> None:
        self.control_server = QLocalServer(self)
        path = str(paths.control_socket())
        QLocalServer.removeServer(path)
        self.control_server.listen(path)
        self.control_server.newConnection.connect(self._on_control_connection)

    def _start_pedal(self) -> None:
        controls = self.config["controls"]
        if not controls.get("pedal_grab") or not controls.get("pedal_device"):
            return
        from ..control.pedal import Pedal

        self.pedal = Pedal(controls["pedal_device"], controls.get("pedal_map", {}), self._pedal_action, grab=True)
        if not self.pedal.start():
            self.notice.emit("error", self.pedal.error)

    def _pedal_action(self, action: str) -> None:
        QTimer.singleShot(0, lambda: self.action(action))

    def _on_control_connection(self) -> None:
        while self.control_server.hasPendingConnections():
            socket = self.control_server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: self._read_control(s))

    def _read_control(self, socket: QLocalSocket) -> None:
        while socket.canReadLine():
            line = bytes(socket.readLine()).decode().strip()
            name, _, argument = line.partition(" ")
            reply = self._handle_external(name, argument)
            socket.write((reply + "\n").encode())
            socket.flush()

    def _handle_external(self, name: str, argument: str) -> str:
        if name == "show":
            self.raiseWindow.emit()
            return "ok"
        if name == "layout":
            if argument.isdigit() and 1 <= int(argument) <= len(LAYOUT_ORDER):
                argument = LAYOUT_ORDER[int(argument) - 1]
            if argument not in LAYOUTS:
                return "layout needs one of: " + ", ".join(LAYOUT_ORDER)
            self.setLayout(argument)
            return "ok"
        if name == "record":
            self.record()
            return "ok"
        if name == "rehearse":
            self.rehearse()
            return "ok"
        if name == "stop":
            self.stop()
            return "ok"
        if name == "flag":
            self.flagCurrent()
            return "ok"
        self.action(name)
        return "ok"

    def _read_recorder(self) -> None:
        while self.recorder_conn.poll():
            try:
                message = self.recorder_conn.recv()
            except (EOFError, OSError):
                self.recorder_notifier.setEnabled(False)
                self.notice.emit("error", "The audio recorder stopped unexpectedly")
                return
            self._on_recorder(message)

    def _on_recorder(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "level":
            self._level = message
            self.levelChanged.emit()
            session_time = message.get("time")
            if session_time is not None and self.session is not None:
                self._time = session_time
                self.session.tick(session_time)
                now = time.monotonic()
                if now - self._last_tick > 0.1:
                    self._last_tick = now
                    self.timeChanged.emit()
        elif kind == "clock":
            self.audio_t0 = message.get("t0_monotonic")
        elif kind == "sources":
            self._sources = message.get("list", [])
            self.devicesChanged.emit()
        elif kind == "stopped":
            self._recorder_stopped = message
        elif kind == "error":
            self.notice.emit("error", message.get("message", "audio error"))
        elif kind == "opened":
            self.notice.emit("info", f"Microphone ready ({message['rate']} Hz, {message['channels']} ch)")

    def _read_engine(self) -> None:
        connection = self.engine_conn
        while connection is not None and connection.poll():
            try:
                message = connection.recv()
            except (EOFError, OSError):
                self.engine_notifier.setEnabled(False)
                self._engine_died()
                return
            self._on_engine(message)

    def _engine_died(self) -> None:
        if self._closing:
            return
        now = time.monotonic()
        self._engine_crashes = [t for t in self._engine_crashes if now - t < 60] + [now]
        if len(self._engine_crashes) > 3:
            self.notice.emit("error", "The speech engine keeps stopping; check Settings → Engines. Recording continues without voice following.")
            return
        if self.session is not None:
            self.session.tracking_active = False
        self._engines = {role: {**info, "state": "error", "detail": "engine stopped"} for role, info in self._engines.items()}
        self.engineChanged.emit()
        self.notice.emit("error", "The speech engine stopped; restarting it. Recording continues.")
        QTimer.singleShot(1500, self._restart_after_crash)

    def _restart_after_crash(self) -> None:
        self._start_engine()
        if self.session is not None:
            self.session.tracking_active = True
        self._update_listening()

    def _on_engine(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "status":
            self._engines = message["engines"]
            self.engineChanged.emit()
        elif kind == "metrics":
            self._engine_metrics = message
            self.monitor.engine_metrics = message
        elif kind == "tts":
            self._play_tts(message)
        elif kind == "gap":
            self.notice.emit("error", f"Voice following fell {message['to'] - message['from']:.0f}s behind and skipped ahead; the CPU is busy (see Resources)")
        elif kind == "command" and not self._recording:
            action = message.get("action")
            if action in ("record", "rehearse") and self._page == "session" and not self._starting_video and not self._finishing:
                self.notice_from_session("command", action)
                QTimer.singleShot(0, self.record if action == "record" else self.rehearse)
        elif self.session is not None and kind in ("vad", "word", "words", "command", "score", "progress"):
            self.session.on_engine(message)

    def _play_tts(self, message: dict) -> None:
        if message.get("error"):
            self.notice.emit("error", f"Reference voice failed: {message['error']}")
            return
        audio = np.frombuffer(message["audio"], dtype=np.float32)
        rate = int(message["rate"])
        text = message["text"]
        started = {"time": self._time}

        def on_start():
            started["time"] = self._time

        def on_end():
            self._ttsDone.emit(started["time"], self._time, text)

        self.player.play(audio, rate, on_start, on_end)

    def _on_tts_done(self, start: float, end: float, text: str) -> None:
        if self.session is not None and self._recording:
            self.session.tts_played(start, end + 0.3, text)

    def state_changed(self, state: str) -> None:
        previous, self._state = self._state, state
        self.cues.play(cue_for_state(previous, state))
        self.stateChanged.emit()

    def position_changed(self, sentence: int, word: int) -> None:
        self._current_sentence = sentence
        if self.script is not None and 0 <= sentence < len(self.script.sentences):
            words = self.script.sentences[sentence].words
            if word >= 0 and word < len(words):
                self._current_word = words[word].index
            elif words:
                self._current_word = words[0].index - 1
        self.positionChanged.emit()

    def sentence_changed(self, sentence: int) -> None:
        self.position_changed(sentence, -1)

    def takes_changed(self) -> None:
        if self.log is None:
            return
        rows = []
        for take in self.log.takes:
            rows.append({
                "id": take.id, "sentence": -1 if take.sentence is None else take.sentence, "number": take.number,
                "status": take.status, "reason": take.reason, "start": take.start, "end": take.end or take.start,
                "score": -1 if take.score is None else round(take.score), "flagged": [f.get("text", "") for f in take.flagged],
                "text": take.text,
            })
        self.takes.set_items(rows)

    def coach_feedback(self, take, flagged: list[dict], deviations: list[dict]) -> None:
        enriched = []
        for entry in flagged:
            guide = self._guide_for_text(entry.get("text", ""))
            enriched.append({**entry, **({"ipa": guide.ipa, "respell": guide.respell, "native": guide.native} if guide else {})})
        self._coach = {
            "take": take.id,
            "sentence": -1 if take.sentence is None else take.sentence,
            "text": take.text,
            "score": take.score,
            "flagged": enriched,
            "deviations": deviations,
            "time": time.time(),
        }
        self.coachChanged.emit()

    def _guide_for_text(self, text: str):
        if not text:
            return None
        key = text.lower().strip(".,;:!?\"'()")
        guide = self.guides.by_key.get(key)
        if guide is None:
            try:
                builder = guide_module.GuideBuilder(packs.get(self.config["general"]["script_language"]), self._native_pack(), self.lexicon)
                guide = builder.guide_for_text(key)
            except Exception:
                return None
        return guide

    def notice_from_session(self, kind: str, text: str) -> None:
        messages = {
            "off-script": f"Off script: “{text}”",
            "end": "End of script. Press Enter to stop, or keep going.",
            "retake": "Practise the word, then read the sentence again" if text == "drill" else "Read that sentence again",
            "auto-flag": f"“{text}” is now flagged for practice",
            "mark": f"Marked: {text}",
            "command": f"Voice: {text}",
            "pickups-done": "Pickups recorded; back to the studio",
            "uncoached": f"“{text}” won't be coached anymore (Settings → Coach to undo)",
            "drill-none": "No warned words in this sentence or the previous one",
            "drill-early": f"Too soon: say “{text}” after the cue",
        }
        if kind == "uncoached":
            self.uncoachedChanged.emit()
            self._rebuild_paragraphs()
        if kind not in ("drill-pass", "drill-miss", "drill-listen"):
            self.notice.emit(kind, messages.get(kind, text))
        if kind == "pickups-done":
            QTimer.singleShot(700, self.stop)
        self.cues.play(cue_for_notice(kind, text))

    def request(self, message: dict) -> None:
        self.processes.send_engine(message)

    def review_changed(self, queue: list[int], index: int) -> None:
        self._review = {"queue": queue, "index": index} if queue else {}
        self.coachChanged.emit()

    def drill_changed(self, drill: dict) -> None:
        if drill:
            guide = self._guide_for_text(drill.get("text", ""))
            if guide:
                drill = {**drill, "ipa": guide.ipa, "respell": guide.respell, "native": guide.native}
        self._drill = drill
        self.drillChanged.emit()

    def marks_changed(self, red: list[int], warned: list[int]) -> None:
        # A map, so each word on the prompter checks itself without scanning a list.
        self._word_marks = {**{str(index): "warn" for index in warned}, **{str(index): "red" for index in red}}
        self.drillChanged.emit()

    def _uncoached(self, key: str) -> bool:
        return key in self.history.uncoached() or self.lexicon.uncoached(key)

    @Slot(result="QVariant")
    def uncoachedWords(self):
        return sorted(self.history.uncoached())

    @Slot(str, bool)
    def setCoached(self, text: str, coached: bool) -> None:
        key = text.strip().lower().strip(".,;:!?\"'()[]")
        if not key:
            return
        self.history.set_coached(key, coached)
        self.history.save()
        self.uncoachedChanged.emit()
        self._rebuild_paragraphs()

    @Slot(int, result=bool)
    def isCoached(self, word_index: int) -> bool:
        if self.script is None or not 0 <= word_index < len(self.script.words):
            return True
        return not self._uncoached(self.script.words[word_index].key)

    @Slot(int)
    def toggleCoached(self, word_index: int) -> None:
        if self.script is None or not 0 <= word_index < len(self.script.words):
            return
        key = self.script.words[word_index].key
        coached = not self.isCoached(word_index)
        if coached and self.lexicon.uncoached(key):
            self.notice.emit("info", f"“{key}” is marked “coach off” in this script's lexicon")
            return
        self.setCoached(key, coached)
        self.notice.emit("info", f"“{key}” will be coached again" if coached else f"“{key}” won't be coached anymore")

    def _native_pack(self):
        try:
            return packs.get(self.config["general"]["native_language"])
        except KeyError:
            return None

    # Projects

    def _projects_dir(self) -> Path:
        return Path(self.config["general"]["projects_dir"]).expanduser()

    def _choose(self, purpose: str, title: str, filters: list, multiple: bool = False) -> None:
        def done(result):
            self._portalResult.emit(purpose, result)

        if portal.available():
            portal.open_file(title, filters, done, multiple=multiple)
        else:
            self._portalResult.emit(purpose, None)

    @Slot()
    def openProjectDialog(self) -> None:
        self._choose("project", "Open project", [("Retake projects", ["*.retake"])])

    @Slot()
    def importScriptsDialog(self) -> None:
        if self.project is None:
            self.notice.emit("error", "Open or create a project first")
            return
        self._choose("import", "Import scripts", [("Scripts", ["*.md", "*.markdown", "*.txt"])], multiple=True)

    def _on_portal(self, purpose: str, result) -> None:
        if result is None:
            self.notice.emit("error", "The file chooser portal is unavailable; pass the project on the command line: retake path/to/project.retake")
            return
        if not result:
            return
        if purpose == "location":
            self.projectLocationChosen.emit(result[0])
        elif purpose == "import":
            self.importScripts(list(result))
        else:
            self.openProject(result[0])

    @staticmethod
    def _local(path: str) -> Path:
        return Path(QUrl(path).toLocalFile() if path.startswith("file://") else path).expanduser()

    def _script_title(self, file: Path) -> str:
        try:
            script = parser.parse_file(file, packs.get(self.config["general"]["script_language"]))
            return script.title or file.stem
        except Exception:
            return file.stem

    @Slot(str, result=str)
    def projectFolderFor(self, location: str) -> str:
        return str(Path(location).expanduser()) if location else str(self._projects_dir())

    @Slot(str)
    def chooseProjectLocation(self, current: str) -> None:
        def done(result):
            self._portalResult.emit("location", result)

        if portal.available():
            portal.open_directory("Where to create the project", done, current or str(self._projects_dir()))
        else:
            self._portalResult.emit("location", None)

    @Slot(str, str)
    def newProject(self, title: str, location: str) -> None:
        title = title.strip()
        if not title or self._busy_recording():
            return
        base = Path(location).expanduser() if location else self._projects_dir()
        project = Project.create(projects.new_directory(base, title), title,
                                 self.config["general"]["script_language"], self.config["general"]["native_language"])
        self._open_project(project)
        self._set_page("project")
        self.notice.emit("info", f"Created {project.title}. Import its scripts with + in the explorer.")

    @Slot(str)
    def openProject(self, path: str) -> None:
        try:
            project = Project.load(self._local(path))
        except Exception as error:
            self.notice.emit("error", f"Could not open the project: {error}")
            return
        self._open_project(project)
        if len(project.items) == 1:
            item = project.items[0]
            self.openItem(item.id, "studio" if item.parts else "prompter")
        elif project.items:
            self.openItem(project.items[0].id, "prompter")
        else:
            self._set_page("project")

    def _busy_recording(self) -> bool:
        """A recording is running, starting or still being saved: the project can't change under it."""
        if self._recording or self._finishing or self._starting_video:
            self.notice.emit("error", "Stop the recording first" if self._recording else "Wait for the recording to finish saving")
            return True
        return False

    def _open_project(self, project: Project) -> None:
        if self._busy_recording():
            project.close()
            return
        for item in project.items:
            recovered = projects.recover_parts(item)
            if recovered:
                self.notice.emit("info", f"Recovered {len(recovered)} unfinished recording(s) in {item.title}")
        self.editor.unload()
        if self.project is not None and self.project is not project:
            self.project.close()
        self.project = project
        self.item = None
        self.itemChanged.emit()
        self._clear_takes()
        recent = [str(project.path)] + [p for p in self.config["general"].get("recent_projects", []) if p != str(project.path)]
        self.config["general"]["recent_projects"] = recent[:12]
        config_module.save(self.config)
        self.recentChanged.emit()
        self.projectChanged.emit()
        self.settingsChanged.emit()
        self._refresh_explorer()

    def importScripts(self, paths_: list[str]) -> None:
        if self.project is None:
            return
        imported = []
        for path in paths_:
            file = self._local(path)
            if file.is_file():
                imported.append(self.project.add_script(file, self._script_title(file)))
        if imported:
            self.notice.emit("info", f"Imported {len(imported)} script(s)")
            self._refresh_explorer()
            self.openItem(imported[0].id, "prompter")

    def attach_window(self, window) -> None:
        self._window = window

    @Slot(str, str)
    def openItem(self, item_id: str, view: str) -> None:
        self._open_item(item_id, view)

    def _open_item(self, item_id: str, view: str, then=None) -> None:
        """Opens an item after the window has shown an "Opening…" overlay: building a long script's
        prompter blocks the UI for a second or more, and the overlay keeps it from looking frozen."""
        if self._recording or self.project is None:
            return
        item = self.project.item(item_id)
        if item is None:
            return
        if self._window is None:
            self._load_item(item, view)
            if then is not None:
                then()
            return
        self._pending_open = (item_id, view, then)
        self._opening = QCoreApplication.translate("Opening", "Opening “%1”…").replace("%1", item.title)
        self.openingChanged.emit()
        # The next sync necessarily carries the overlay; the render thread then draws it (and keeps the
        # spinner turning) while this thread is busy. The timer covers a window that isn't drawing.
        if not self._awaiting_sync:
            self._awaiting_sync = True
            self._window.afterSynchronizing.connect(self._synced, Qt.ConnectionType.QueuedConnection)
        self._open_timer.start()

    def _run_pending_open(self) -> None:
        self._open_timer.stop()
        if self._awaiting_sync:
            self._awaiting_sync = False
            self._window.afterSynchronizing.disconnect(self._synced)
        pending, self._pending_open = self._pending_open, None
        if pending is None:
            return
        item_id, view, then = pending
        try:
            item = self.project.item(item_id) if self.project is not None and not self._recording else None
            if item is not None:
                self._load_item(item, view)
                if then is not None:
                    then()
        except Exception as error:
            traceback.print_exc()
            self.notice.emit("error", f"Couldn't open this recording: {type(error).__name__}: {error}")
        finally:
            self._opening = ""
            self.openingChanged.emit()

    def _load_item(self, item: Item, view: str) -> None:
        self.editor.save()
        self.item = item
        self.itemChanged.emit()
        self._pickup = []
        self._review = {}
        self.coachChanged.emit()
        self._expanded.add(item.id)
        if item.parts:
            self._sync_snapshot(item)
        if view.startswith("part:") or view == "studio":
            self._clear_takes()
            self.editor.load(item)
            self._set_page("editor")
            if view.startswith("part:"):
                part = next((p for p in item.parts if p.index == int(view.split(":")[1])), None)
                if part is not None:
                    self.seekEditor.emit(part.start)
        if view == "prompter":
            self._clear_takes()
            if item.script_file is None or not item.script_file.exists():
                self.notice.emit("error", f"The script of {item.title} isn't in the project's scripts folder anymore")
                return
            try:
                self._load_script(item.script_file)
            except Exception as error:
                self.notice.emit("error", f"Could not read the script: {error}")
                return
            self._resume_position(item)
            self.setLayout(self._layout_named(self.config["general"].get("layout")))
            self._watch(item.script_file)
            self.runPreflight()
            self._set_page("session")
            self._state = "ready"
            self.stateChanged.emit()
        self.settingsChanged.emit()
        self._refresh_explorer()
        self._phoneUpdate.emit()

    def _resume_position(self, item: Item) -> None:
        """Opens the prompter on the first sentence that has no good take yet."""
        if self.script is None:
            return
        done = {t.sentence for t in item.load_takes().takes if t.status == COMPLETE and t.sentence is not None}
        target = next((s.index for s in self.script.sentences if s.trackable and s.index not in done), None)
        if target is not None:
            self._current_sentence = target
            words = self.script.sentences[target].words
            self._current_word = words[0].index - 1 if words else -1
            self.positionChanged.emit()

    def _watch(self, file: Path) -> None:
        from PySide6.QtCore import QFileSystemWatcher

        if self._watcher is not None:
            self._watcher.deleteLater()
        self._watcher = QFileSystemWatcher([str(file)], self)
        self._watcher.fileChanged.connect(self._script_file_changed)

    @Slot(str)
    def showView(self, view: str) -> None:
        """Record or Studio for the open script."""
        if self.item is None or self._page == ("session" if view == "record" else "editor"):
            return
        if self._recording or self._starting_video or self._finishing:
            self.notice.emit("info", "Stop the recording first (Enter)")
            return
        self.openItem(self.item.id, "prompter" if view == "record" else "studio")

    @Slot()
    def toggleView(self) -> None:
        if self._page in ("session", "editor"):
            self.showView("studio" if self._page == "session" else "record")

    @Slot("QVariant")
    def rerecord(self, sentences) -> None:
        """Pickups: back to the prompter with only these sentences queued."""
        item = self.editor.item
        if item is None or not sentences:
            return
        if self.editor.dirty:
            self.editor.save()
        queue = sorted({int(s) for s in sentences})
        self._open_item(item.id, "prompter", lambda: self._queue_pickups(queue))

    def _queue_pickups(self, queue: list[int]) -> None:
        if self.script is None:
            return
        queue = [s for s in queue if 0 <= s < len(self.script.sentences)]
        if not queue:
            return
        self._pickup = queue
        self._review = {"queue": queue, "index": 0, "pending": True}
        self.coachChanged.emit()
        self.jumpTo(queue[0])
        self.notice.emit("info", f"Pickups: {self._sentence_list(queue)}. Press Space to record them.")

    @staticmethod
    def _sentence_list(queue: list[int]) -> str:
        return ", ".join(f"S{s + 1}" for s in queue[:8]) + (" …" if len(queue) > 8 else "")

    @Slot()
    def cancelPickup(self) -> None:
        if self._recording or not self._pickup:
            return
        self._pickup = []
        self._review = {}
        self.coachChanged.emit()
        if self.item is not None and self.item.parts:
            self.openItem(self.item.id, "studio")

    @Slot(str, bool)
    def setExpanded(self, item_id: str, expanded: bool) -> None:
        if expanded:
            self._expanded.add(item_id)
        else:
            self._expanded.discard(item_id)
        self._refresh_explorer()

    @Slot(str, str)
    def renameItem(self, item_id: str, title: str) -> None:
        if self.project is not None:
            self.project.rename_item(item_id, title)
            self._refresh_explorer()
            self.itemChanged.emit()

    @Slot(str)
    def removeItem(self, item_id: str) -> None:
        if self.project is None or self._recording:
            return
        if self.item is not None and self.item.id == item_id:
            self.item = None
            self.itemChanged.emit()
            self.editor.unload()
            self._set_page("project")
        self.project.remove_item(item_id)
        self.notice.emit("info", "Removed from the project; its folder is still on disk")
        self._refresh_explorer()

    @Slot(str)
    def deleteRecordings(self, item_id: str) -> None:
        """Moves an item's recordings, takes, edit and exports to the trash; the script stays."""
        from PySide6.QtCore import QFile

        item = self.project.item(item_id) if self.project else None
        if item is None or self._recording or self._finishing:
            return
        if self.editor.item is not None and self.editor.item.id == item_id:
            self.editor.unload()
        failed = [path.name for path in item.recording_files() if not QFile.moveToTrash(str(path))]
        if failed:
            self.notice.emit("error", f"Couldn't move to the trash: {', '.join(failed)}")
            return
        item.forget_recordings()
        self._script_meta.pop(str(item.script_file), None)
        self.notice.emit("info", f"Recordings of {item.title} moved to the trash")
        self._refresh_explorer()
        if self.item is not None and self.item.id == item_id:
            self.openItem(item_id, "prompter")

    @Slot(str, int)
    def deleteRecording(self, item_id: str, part_index: int) -> None:
        """Moves one recording to the trash; the later ones close the gap and the edit keeps the rest."""
        from PySide6.QtCore import QFile

        item = self.project.item(item_id) if self.project else None
        if item is None or self._recording or self._finishing:
            return
        if len(item.parts) <= 1:
            self.deleteRecordings(item_id)
            return
        showing = self.editor.item is not None and self.editor.item.id == item_id
        if showing:
            self.editor.unload()
        files = item.remove_part(part_index)
        failed = [path.name for path in files if not QFile.moveToTrash(str(path))]
        if failed:
            self.notice.emit("error", f"Couldn't move to the trash: {', '.join(failed)}")
        self._script_meta.pop(str(item.script_file), None)
        self.notice.emit("info", f"Recording {part_index} of {item.title} moved to the trash")
        self._refresh_explorer()
        if showing:
            self.openItem(item_id, "studio")

    @Slot(str, int)
    def playRecording(self, item_id: str, part_index: int) -> None:
        """Opens one raw recording (its video, or its audio) in the system's player."""
        from PySide6.QtGui import QDesktopServices

        item = self.project.item(item_id) if self.project else None
        part = next((p for p in item.parts if p.index == part_index), None) if item else None
        if part is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(part.video or part.audio)))

    @Slot(str)
    def reimportItem(self, item_id: str) -> None:
        if self.project is None:
            return
        if self.project.reimport(item_id):
            self.notice.emit("info", "Script re-imported from the original file")
            item = self.project.item(item_id)
            if item is not None and item.parts:
                self._sync_snapshot(item)
            if self.item is not None and self.item.id == item_id:
                self.openItem(item_id, "studio" if self._page == "editor" else "prompter")
        else:
            self.notice.emit("error", "The original file isn't there anymore")
        self._refresh_explorer()

    @Slot(str)
    def revealItem(self, item_id: str) -> None:
        from PySide6.QtGui import QDesktopServices

        target = self.project.directory if self.project and not item_id else (self.project.item(item_id).folder if self.project and self.project.item(item_id) else None)
        if target is not None:
            target.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    @Slot(str)
    def openExports(self, item_id: str) -> None:
        from PySide6.QtGui import QDesktopServices

        item = self.project.item(item_id) if self.project else None
        if item is not None:
            item.out_dir.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(item.out_dir)))

    @Slot()
    def toggleExplorer(self) -> None:
        self._explorer_visible = not self._explorer_visible
        self.config["general"]["explorer"] = self._explorer_visible
        config_module.save(self.config)
        self.projectChanged.emit()

    def _script_info(self, item: Item) -> tuple[str, int]:
        file = item.script_file
        if file is None or not file.exists():
            return item.title, 0
        mtime = file.stat().st_mtime
        cached = self._script_meta.get(str(file))
        if cached and cached[0] == mtime:
            return cached[1], cached[2]
        try:
            script = parser.parse_file(file, packs.get(self.project.language))
            info = (script.title or item.title, sum(1 for s in script.sentences if s.trackable))
        except Exception:
            info = (item.title, 0)
        self._script_meta[str(file)] = (mtime, *info)
        return info

    @staticmethod
    def _length(seconds: float) -> str:
        minutes, rest = divmod(int(round(seconds)), 60)
        return f"{minutes}:{rest:02d}"

    def _refresh_explorer(self) -> None:
        if self.project is None:
            self.explorer.set_items([])
            self.explorerChanged.emit()
            return
        rows = []
        current = self.item.id if self.item else ""
        for item in self.project.items:
            _, total = self._script_info(item)
            status = item.status()
            detail = f"{status['recorded']}/{total}" if total else ""
            if status["duration"]:
                detail += ("  ·  " if detail else "") + self._length(status["duration"])
            expanded = item.id in self._expanded
            rows.append({"kind": "script", "depth": 0, "id": item.id, "part": 0, "title": item.title, "detail": detail,
                         "expanded": expanded, "expandable": bool(item.parts), "current": item.id == current})
            if expanded:
                rows += self._item_children(item)
        self.explorer.set_items(rows)
        self.explorerChanged.emit()

    def _item_children(self, item: Item) -> list[dict]:
        rows = []
        recordings = pickups = 0
        for part in item.parts:
            if part.kind == "pickup":
                pickups += 1
                label = QCoreApplication.translate("Explorer", "Pickups %1").replace("%1", str(pickups))
                if part.sentences:
                    label += f" ({self._sentence_list(list(part.sentences))})"
            else:
                recordings += 1
                label = QCoreApplication.translate("Explorer", "Recording %1").replace("%1", str(recordings))
            when = part.created[5:16].replace("T", " ") if part.created else ""
            rows.append({"kind": "part", "depth": 1, "id": item.id, "part": part.index, "title": label,
                         "detail": f"{when}  ·  {self._length(part.duration)}" if when else self._length(part.duration),
                         "expanded": False, "expandable": False, "current": False})
        exported = [f for f in item.out_dir.iterdir() if f.is_file()] if item.out_dir.is_dir() else []
        if exported:
            rows.append({"kind": "exports", "depth": 1, "id": item.id, "part": 0, "title": QCoreApplication.translate("Explorer", "Exports"),
                         "detail": str(len(exported)), "expanded": False, "expandable": False, "current": False})
        return rows

    @Slot(int)
    def explorerActivate(self, row: int) -> None:
        entry = self.explorer.get(row)
        if not entry:
            return
        kind = entry["kind"]
        if kind == "script":
            self.openItem(entry["id"], "prompter")
        elif kind == "part":
            self.openItem(entry["id"], f"part:{entry['part']}")
        elif kind == "exports":
            self.openExports(entry["id"])

    def _clear_takes(self) -> None:
        self.log = None
        self._rehearsal = False
        self.takes.set_items([])
        self._coach = {}
        self.coachChanged.emit()

    def _script_file_changed(self, path: str) -> None:
        if self._recording:
            self.notice.emit("info", "The script changed on disk; it will reload after this recording")
            return
        QTimer.singleShot(300, lambda: self._reload_script(Path(path)))

    def _reload_script(self, path: Path) -> None:
        if path.exists():
            self._load_script(path)
            self._watcher.addPath(str(path))
            self.notice.emit("info", "Script reloaded")
            self.runPreflight()

    def _load_script(self, file: Path) -> None:
        pack = packs.get(self.config["general"]["script_language"])
        self.script = parser.parse_file(file, pack)
        self.script_path = file
        self.lexicon = Lexicon.for_script(file)
        builder = guide_module.GuideBuilder(pack, self._native_pack(), self.lexicon)
        self.guides = builder.build(self.script)
        self._current_sentence = next((s.index for s in self.script.sentences if s.trackable or s.kind == ADLIB), 0)
        self._current_word = -1
        self._rebuild_paragraphs()
        self.scriptChanged.emit()
        self.positionChanged.emit()

    def _flagged(self, key: str) -> bool:
        return self.lexicon.is_flagged(key) or key in self.history.flagged()

    def _rebuild_paragraphs(self) -> None:
        if self.script is None:
            self.paragraphs.set_items([])
            return
        scope = self.config["guides"].get("scope", "hard")
        section_seen: set[int] = set()
        rows = []
        flagged_keys = self.history.flagged()
        for paragraph in self.script.paragraphs:
            sentences = []
            kind = "spoken"
            note = ""
            for index in paragraph.sentences:
                sentence = self.script.sentences[index]
                if sentence.kind == ADLIB:
                    kind = ADLIB
                    note = sentence.note
                sentences.append({"index": index, "kind": sentence.kind, "tokens": [self._token(t, scope, flagged_keys) for t in sentence.tokens]})
            section_title, level = "", 0
            if paragraph.section >= 0 and paragraph.section not in section_seen:
                section_seen.add(paragraph.section)
                section = self.script.sections[paragraph.section]
                section_title, level = section.title, section.level
            rows.append({"paragraph": paragraph.index, "section": section_title, "sectionLevel": level, "kind": kind, "note": note, "sentences": sentences})
        self.paragraphs.set_items(rows)

    def _token(self, token, scope: str, flagged_keys: set[str]) -> dict:
        if token.kind != WORD:
            return {"kind": token.kind, "text": token.text, "value": token.value, "word": -1}
        word = token.word
        guide = self.guides.for_word(word)
        flagged = self.lexicon.is_flagged(word.key) or word.key in flagged_keys
        show = guide_module.visible(guide, scope, flagged) and not self._uncoached(word.key)
        return {
            "kind": WORD,
            "text": word.display,
            "word": word.index,
            "sentence": word.sentence,
            "emphasis": word.emphasis,
            "flagged": flagged,
            "guide": show,
            "ipa": guide.ipa if guide else "",
            "respell": guide.respell if guide else "",
            "native": guide.native if guide else "",
        }

    @Slot()
    def closeProject(self) -> None:
        """Home only shows with no project open."""
        if self._busy_recording():
            return
        self.editor.unload()
        if self.project is not None:
            self.project.close()
        self.project = None
        self.item = None
        self.script = None
        self.script_path = None
        self._clear_takes()
        self.itemChanged.emit()
        self.projectChanged.emit()
        self.scriptChanged.emit()
        self._refresh_explorer()
        self._set_page("start")

    def _set_page(self, page: str) -> None:
        self._page = page
        self.pageChanged.emit()
        self._phoneUpdate.emit()
        self._update_listening()

    @Slot()
    def record(self) -> None:
        self._begin(rehearsal=False)

    @Slot()
    def rehearse(self) -> None:
        self._begin(rehearsal=True)

    def _begin(self, rehearsal: bool) -> None:
        if self._recording or self._finishing or self._starting_video or self._page != "session":
            return
        if self.script is None or self.item is None:
            self.notice.emit("error", "Open a script first")
            return
        self._rehearsal = rehearsal
        pickup = [] if rehearsal else list(self._pickup)
        self.log = TakeLog()
        if not rehearsal:
            self._sync_snapshot(self.item)
            self.part_index, self.part_audio = self.item.next_part()
            self.item.folder.mkdir(parents=True, exist_ok=True)
            self.log = self.item.recording_log(self.part_index)
        coach = self.config["coach"]
        strictness = self.config["strictness"]
        settings = SessionSettings(
            rehearsal=rehearsal,
            coach=CoachSettings(
                enabled=bool(coach.get("enabled", True)) and self._engines.get("scorer", {}).get("engine") == "wav2vec2",
                require=float(coach.get("require") or 0) or None,
                drill_times=int(coach.get("drill_times", 3)),
                threshold=float(coach.get("threshold", 55)),
                timing=coach.get("timing", "live"),
                auto_flag_misses=int(coach.get("auto_flag_misses", 3)),
            ),
            extra_speech=strictness.get("extra_speech", "between"),
            deviations=strictness.get("deviations", "warn"),
        )
        pack = packs.get(self.config["general"]["script_language"])
        listener = _Listener(self)
        self.session = Session(self.log, settings, listener, self.script, pack, self._native_pack(), self.history, self._current_sentence, self.lexicon,
                               pickup=pickup)
        self._coach = {}
        self._review = {}
        self._time = 0.0
        self.coachChanged.emit()
        self._recorder_stopped = None
        self.audio_t0 = None
        if not rehearsal:
            # Cameras take a moment to start; reading starts only once the video records, so the first
            # words of a part are never left without picture. The wait is set up before the camera is
            # asked to record: some encoders report recording at once, inside that call.
            self._starting_video = QCoreApplication.translate("Recording", "Starting the video recording…")
            self.startingVideoChanged.emit()
            if self._start_video():
                if self._starting_video:
                    self._video_timer.start()
                return
            self._starting_video = ""
            self.startingVideoChanged.emit()
        self._go_live()

    def _video_timed_out(self) -> None:
        if self._starting_video:
            self.notice.emit("error", "The video didn't start in time; recording audio only")
            self._go_live()

    def _go_live(self) -> None:
        self._video_timer.stop()
        if self._starting_video:
            self._starting_video = ""
            self.startingVideoChanged.emit()
        if self.session is None or self._recording:
            return
        rehearsal = self._rehearsal
        self.processes.send_recorder({"type": "start", "path": None if rehearsal else str(self.part_audio)})
        self._recording = True
        self._update_listening()
        self.session.start()
        if not rehearsal:
            self.resource_log = ResourceLog(paths.recording_log(f"{self._part_name()}.resources.csv"))
            self.monitor.recording_files = [self.part_audio]
        self.stateChanged.emit()
        self.takes_changed()

    def _part_name(self) -> str:
        """How a recording's diagnostics files are named in the log folder."""
        return f"{projects.slug(self.project.title)}-{self.item.id}-part-{self.part_index:03d}"

    def _sync_snapshot(self, item: Item) -> None:
        """Keeps the item's snapshot equal to its script, re-pointing earlier takes when it changed."""
        result = projects.sync_script(item)
        if result is None:
            return
        if result.reworded:
            self.notice.emit("info", f"Reworded since you recorded them: {self._sentence_list(result.reworded)}. "
                                     "Their old takes stay in the edit; Re-record changed in the studio redoes them.")
        if result.lost:
            self.notice.emit("info", f"{result.lost} earlier take(s) no longer match a sentence and were set aside")

    def _start_video(self) -> bool:
        """Starts the part's video; True when it's on its way and will report through _videoStarted."""
        source = self.config["camera"].get("source", "none")
        try:
            if source == "device":
                if not QMediaDevices.videoInputs():
                    raise RuntimeError("no camera found")
                self.camera_file = self.item.folder / f"part-{self.part_index:03d}.mp4"
                self.cameraRecord.emit(str(self.camera_file))
                self.monitor.bitrate_mbps = 10.0
                return True
            if source == "phone" and self._prepare_phone():
                threading.Thread(target=self._start_phone, daemon=True).start()
                return True
        except Exception as error:
            self.notice.emit("error", f"Video recording did not start: {error}. Recording audio only.")
        return False

    def _prepare_phone(self) -> bool:
        if not phone_video.available():
            self.notice.emit("error", "scrcpy is not installed (it's in the official repositories: pacman -S scrcpy); recording audio only")
            return False
        name = f"part-{self.part_index:03d}"
        video = self.item.folder
        sink = phone_video.loopback_device() if self.config["phone"].get("preview", False) else None
        phone_settings, note = self._phone_settings()
        if note:
            self.notice.emit("info", f"Phone camera: {note}")
        container = phone_settings.get("container", "mkv")
        self.phone = phone_video.PhoneRecorder(video / f"{name}.{container}", phone_settings, paths.recording_log(f"{self._part_name()}.scrcpy.log"), sink)
        # Let go of the virtual camera so the recording's scrcpy can give it its own picture size.
        self.phone_frames.stop()
        self.monitor.bitrate_mbps = 40.0
        return True

    def _start_phone(self) -> None:
        recorder = self.phone
        with self._phone_lock:
            # The phone camera serves one scrcpy at a time: the preview hands it to the recording.
            if self.phone_preview is not None:
                self.phone_preview.stop()
                self.phone_preview = None
        try:
            try:
                recorder.start()
            except RuntimeError:
                if recorder.sink is None:
                    raise
                recorder.sink = None
                recorder.start()
                self.notice.emit("info", "The phone records, but the live preview couldn't run alongside it")
            self.phoneFeedChanged.emit()
            self._videoStarted.emit(True)
        except Exception as error:
            self.notice.emit("error", f"Phone camera failed: {error}. Recording audio only.")
            if self.phone is recorder:
                self.phone = None
            self._videoStarted.emit(False)

    @Slot(QObject)
    def setPhoneOutput(self, output: QObject) -> None:
        sink = output.property("videoSink")
        if isinstance(sink, QVideoSink):
            self.phone_frames.add_sink(sink)

    def _restart_phone_frames(self) -> None:
        device = phone_video.loopback_device()
        if self._phone_mode() and device and (self.phone_preview is not None or self.phone is not None):
            self.phone_frames.start(device, phone_video.portrait(self._phone_config()))
        else:
            self.phone_frames.stop()

    # Phones: each one is known by its adb serial, with its detected cameras and its own settings.

    PHONE_GLOBAL_KEYS = ("serial", "preview")

    def _phone_cameras_file(self) -> Path:
        return paths.cache_dir() / "phone-cameras.json"

    def _load_known_phones(self) -> dict[str, dict]:
        import json

        try:
            return dict(json.loads(self._phone_cameras_file().read_text()).get("phones", {}))
        except (OSError, ValueError, AttributeError):
            return {}

    def _forget_settings(self) -> None:
        self._settings_cache = None

    def _connected_phones(self) -> list:
        return [p for p in phone_video.phones() if p.state == "device"] if phone_video.available() else []

    def _resolve_active_phone(self) -> str:
        previous = self._active_serial
        self._resolve_serial()
        if self._active_serial != previous:
            self._settings_cache = None
        return self._active_serial

    def _resolve_serial(self) -> str:
        chosen = self.config["phone"].get("serial") or ""
        if chosen:
            self._active_serial = chosen
        else:
            connected = self._connected_phones()
            self._active_serial = connected[0].serial if connected else self._active_serial
        return self._active_serial

    @property
    def _phone_cameras(self) -> list:
        entry = self._known_phones.get(self._active_serial) or {}
        return [phone_video.Camera.from_dict(c) for c in entry.get("cameras", [])]

    def _phone_config(self) -> dict:
        """Phone settings for the active phone: its own values over the shared defaults."""
        phone = self.config["phone"]
        merged = {k: v for k, v in phone.items() if k != "phones"}
        merged.update((phone.get("phones") or {}).get(self._active_serial, {}))
        return merged

    @Slot()
    def detectPhoneCameras(self) -> None:
        if self._detecting or not phone_video.available():
            return
        serial = self._resolve_active_phone()
        if not serial:
            return
        self._detecting = True
        self.phoneCamerasChanged.emit()
        model = next((p.model for p in phone_video.phones() if p.serial == serial), "")

        def work():
            cameras, name = phone_video.detect_cameras(serial)
            self._phoneCamerasFound.emit({"serial": serial, "model": name or model, "cameras": [c.as_dict() for c in cameras]})

        threading.Thread(target=work, daemon=True).start()

    def _set_phone_cameras(self, found) -> None:
        import json

        self._detecting = False
        if not found.get("cameras"):
            self.phoneCamerasChanged.emit()
            self.notice.emit("error", "Couldn't read the phone's cameras; is it connected with USB debugging allowed?")
            return
        previous = self._known_phones.get(found["serial"], {})
        self._known_phones[found["serial"]] = {"model": found.get("model") or previous.get("model", ""), "cameras": found["cameras"]}
        try:
            self._phone_cameras_file().write_text(json.dumps({"phones": self._known_phones}, indent=1))
        except OSError:
            pass
        self.phoneCamerasChanged.emit()
        self.settingsChanged.emit()

    def _phone_settings(self) -> tuple[dict, str]:
        self._resolve_active_phone()
        options, note = phone_video.resolve(self._phone_config(), self._phone_cameras)
        if self._active_serial:
            options["serial"] = self._active_serial
        return options, note

    def _phone_rows(self) -> list[dict]:
        connected = {p.serial: p for p in self._connected_phones()}
        rows = []
        for serial in dict.fromkeys(list(connected) + list(self._known_phones)):
            model = self._known_phones.get(serial, {}).get("model", "") or (connected[serial].model if serial in connected else "") or serial
            state = "" if serial in connected else "  · " + QCoreApplication.translate("Phone", "not connected")
            rows.append({"serial": serial, "label": f"{model}{state}", "connected": serial in connected})
        return rows

    def _camera_rows(self) -> list[dict]:
        rows = []
        facing_count: dict[str, int] = {}
        for camera in self._phone_cameras:
            facing_count[camera.facing] = facing_count.get(camera.facing, 0) + 1
            number = facing_count[camera.facing]
            name = {"back": QCoreApplication.translate("Phone", "Back"), "front": QCoreApplication.translate("Phone", "Front")}.get(camera.facing, camera.facing.title())
            fps = [{"value": f, "label": f"{f} fps"} for f in sorted(set(camera.fps), reverse=True)]
            for size, rates in camera.high_speed:
                for rate in rates:
                    if rate not in camera.fps and all(entry["value"] != rate for entry in fps):
                        top = max((s for s, r in camera.high_speed if rate in r), key=lambda s: int(s.split("x")[0]) * int(s.split("x")[1]))
                        fps.append({"value": rate, "label": QCoreApplication.translate("Phone", "%1 fps · high speed, up to %2").replace("%1", str(rate)).replace("%2", top.replace("x", "×"))})
            rows.append({
                "id": camera.id,
                "facing": camera.facing,
                "label": f"{name}{' ' + str(number) if number > 1 else ''} · {camera.size.replace('x', '×')} · " + QCoreApplication.translate("Phone", "up to %1 fps").replace("%1", str(max(camera.fps, default=30))),
                "sizes": [{"value": size, "label": phone_video.describe_size(size)} for size in phone_video.video_sizes(camera)],
                "fps": fps,
            })
        return rows

    def _stop_phone_preview(self, then_update: bool = False) -> None:
        preview, self.phone_preview = self.phone_preview, None
        self.phone_frames.stop()

        def close():
            if preview is not None:
                with self._phone_lock:
                    preview.stop()
            if then_update:
                self._phoneUpdate.emit()

        threading.Thread(target=close, daemon=True).start()

    def _restart_phone_preview(self) -> None:
        """A phone setting changed: the preview reopens the camera with it."""
        self._stop_phone_preview(then_update=True)

    def _phone_mode(self) -> bool:
        return self.config["camera"].get("source") == "phone"

    def _update_phone_preview(self) -> None:
        if self._phone_mode() and phone_video.available():
            self._resolve_active_phone()
            if self._active_serial and not self._phone_cameras:
                self.detectPhoneCameras()
        wanted = (self._page == "session" and self._phone_mode() and not self._recording and not self._finishing and not self._starting_video
                  and phone_video.available() and phone_video.loopback_device() is not None)
        running = self.phone_preview is not None
        if wanted and not running:
            preview = phone_video.PhoneRecorder(None, self._phone_settings()[0], paths.cache_dir() / "phone-preview.log", phone_video.loopback_device())
            self.phone_preview = preview
            self.phone_frames.stop()

            def start():
                with self._phone_lock:
                    if self.phone_preview is not preview:
                        return
                    try:
                        preview.start()
                    except Exception as error:
                        self.phone_preview = None
                        self.notice.emit("error", f"Phone preview: {error}")
                        return
                self.phoneFeedChanged.emit()

            threading.Thread(target=start, daemon=True).start()
        elif not wanted and running and not self._recording:
            self._stop_phone_preview()
        if not wanted and self.phone is None:
            self.phone_frames.stop()

    @Slot(result=str)
    def phoneStatus(self) -> str:
        if not phone_video.available():
            return QCoreApplication.translate("Phone", "scrcpy is not installed: pacman -S scrcpy")
        found = phone_video.phones()
        if not found:
            return QCoreApplication.translate("Phone", "No phone found. Connect it by USB and turn on USB debugging (Developer options).")
        lines = []
        if phone_video.loopback_device() is None:
            lines.append(QCoreApplication.translate("Phone", "No virtual camera yet, so the camera panel can't show the phone. Set it up once:") + "\n" + phone_video.SETUP)
        for device in found:
            if device.state == "device":
                lines.append(QCoreApplication.translate("Phone", "%1 is ready").replace("%1", device.model or device.serial))
            elif device.state == "unauthorized":
                lines.append(QCoreApplication.translate("Phone", "%1: accept the USB debugging prompt on the phone").replace("%1", device.serial))
            else:
                lines.append(f"{device.serial}: {device.state}")
        return "\n".join(lines)

    @Slot()
    def cameraRecordingFinished(self) -> None:
        self.camera_finished = True

    @Slot(str)
    def cameraRecordingStarted(self, location: str) -> None:
        self.camera_finished = False
        self.camera_started = time.monotonic()
        if location:
            self.camera_file = Path(QUrl(location).toLocalFile() if location.startswith("file:") else location)
        if self._starting_video:
            self._go_live()

    @Slot()
    def stop(self) -> None:
        if not self._recording or self.session is None:
            return
        self.session.stop()
        self._recording = False
        self._update_listening()
        self.processes.send_recorder({"type": "stop"})
        if self.camera_file:
            self.cameraStop.emit()
        self.stateChanged.emit()
        if self.resource_log:
            self.resource_log.close()
            self.resource_log = None
        self.monitor.recording_files = []
        if self._rehearsal or self.part_audio is None or self.item is None:
            self.notice.emit("info", "Rehearsal finished")
            self._state = "ready"
            self.stateChanged.emit()
            self._phoneUpdate.emit()
            return
        self._set_finishing(QCoreApplication.translate("Finishing", "Saving the audio…"))
        job = {"item": self.item.id, "index": self.part_index, "audio": str(self.part_audio), "pickup": list(self._pickup)}
        self.part_audio = None
        threading.Thread(target=self._finalize, args=(job,), daemon=True).start()

    def _set_finishing(self, step: str) -> None:
        self._finishing = step
        self.finishingChanged.emit()

    def _finalize(self, job: dict) -> None:
        deadline = time.time() + 10
        while self._recorder_stopped is None and time.time() < deadline:
            time.sleep(0.05)
        video_path = None
        video_t0 = None
        from_phone = self.phone is not None
        if self.phone is not None:
            self._finishStep.emit(QCoreApplication.translate("Finishing", "Finishing the phone recording…"))
            video_path = self.phone.stop()
            video_t0 = self.phone.started
            self.phone = None
        if self.camera_file is not None:
            self._finishStep.emit(QCoreApplication.translate("Finishing", "Finishing the camera recording…"))
            video_t0 = self.camera_started
            deadline = time.time() + 15
            while time.time() < deadline and not self.camera_finished:
                time.sleep(0.1)
            if self.camera_file.exists() and self.camera_file.stat().st_size > 0:
                video_path = self.camera_file
            self.camera_file = None
        job["trim"] = video_path is not None and from_phone
        audio = Path(job["audio"])
        duration = float((self._recorder_stopped or {}).get("duration", 0.0)) or projects.audio_duration(audio)
        job.update({"duration": duration, "t0": self.audio_t0, "video": None, "offset": 0.0, "method": "none"})
        if video_path is not None and video_path.exists():
            from ..edit import media

            self._finishStep.emit(QCoreApplication.translate("Finishing", "Lining up the video with the audio…"))
            if job["trim"]:
                try:
                    media.prepare_phone_video(video_path)
                except RuntimeError as error:
                    self.notice.emit("error", f"Couldn't prepare the phone video: {error}")
            offset, method = media.estimate_offset(audio, video_path, self.audio_t0, video_t0=video_t0)
            video_path.with_name(video_path.name + ".ts").unlink(missing_ok=True)
            job.update({"video": str(video_path), "offset": offset, "method": method})
            if job.get("trim"):
                job["segments"] = self._trim_video(video_path, duration, offset)
        self._finishStep.emit(QCoreApplication.translate("Finishing", "Finding the pauses between words…"))
        try:
            from ..edit import media

            media.peaks(audio, 100, paths.cache_dir() / "peaks")
        except Exception as error:
            self.notice.emit("error", f"Couldn't read the recording's pauses: {error}")
        self._finishStep.emit(QCoreApplication.translate("Finishing", "Opening the studio…"))
        self._finalized.emit(job)

    def _trim_video(self, video: Path, duration: float, offset: float) -> list[dict] | None:
        """Cuts the phone video's waiting and long pauses out, losslessly; returns its new time map."""
        from ..edit import trim

        pauses = [(m.start, m.end) for m in (self.log.markers_of(kinds.PAUSE) if self.log else [])]
        self._finishStep.emit(QCoreApplication.translate("Finishing", "Trimming the waiting and pauses from the video…"))
        try:
            segments = trim.trim(video, duration, offset, pauses)
        except Exception as error:
            self.notice.emit("error", f"Couldn't trim the video ({error}); it's kept whole")
            return None
        return [s.as_dict() for s in segments] if segments else None

    def _on_finalized(self, job) -> None:
        # Let the "Opening the studio…" step paint before the editor loads on this thread.
        QTimer.singleShot(30, lambda: self._open_finished(dict(job)))

    def _open_finished(self, job: dict) -> None:
        self._phoneUpdate.emit()
        self._state = "stopped"
        self.stateChanged.emit()
        try:
            item = self.project.item(job["item"]) if self.project else None
            if item is None:
                return
            index, audio = job["index"], Path(job["audio"])
            part_log = item.unfinished_recording(index) or self.log or TakeLog()
            pickup = job.get("pickup") or []
            had_edit = item.load_edit() is not None
            added = item.finish_recording(
                part_log, index, audio, job["duration"], kind="pickup" if pickup else "recording",
                video=Path(job["video"]) if job.get("video") else None, video_offset=job.get("offset", 0.0),
                video_method=job.get("method", "none"), t0_monotonic=job.get("t0"), sentences=pickup or None,
                engines={role: info.get("engine") for role, info in self._engines.items()}, video_segments=job.get("segments"),
            )
            recorded = {t.sentence for t in added if t.status == COMPLETE and t.sentence is not None}
            self.item = item
            self.itemChanged.emit()
            self._pickup = []
            self._review = {}
            self.coachChanged.emit()
            self._clear_takes()
            self.editor.load(item)
            if had_edit and recorded:
                updated = self.editor.apply_recording(recorded)
                self.editor.save()
                if updated:
                    self.notice.emit("info", f"New takes swapped in for {self._sentence_list(updated)}")
            self._set_page("editor")
            self._refresh_explorer()
        finally:
            self._set_finishing("")

    @Slot(str)
    def action(self, name: str) -> None:
        if name == "toggle_pause" and not self._recording:
            self.record()
            return
        if self.session is None or not self._recording:
            if name in ("next", "back") and self.script is not None and self._page == "session":
                self._preview_move(1 if name == "next" else -1)
            elif name == "drill":
                self.notice.emit("info", "Drills run while recording or rehearsing (Space or Shift+Space)")
            return
        self.session.handle(name, time=self._time)

    def _preview_move(self, delta: int) -> None:
        script = self.script
        index = self._current_sentence
        target = script.next_sentence(index) if delta > 0 else script.previous_sentence(index)
        if target is not None:
            self._current_sentence = target
            words = script.sentences[target].words
            self._current_word = words[0].index - 1 if words else self._current_word
            self.positionChanged.emit()

    @Slot(int)
    def jumpTo(self, sentence: int) -> None:
        if self.session is not None and self._recording:
            self.session.handle("goto", sentence, time=self._time)
        elif self.script is not None and 0 <= sentence < len(self.script.sentences):
            self._current_sentence = sentence
            words = self.script.sentences[sentence].words
            self._current_word = words[0].index - 1 if words else -1
            self.positionChanged.emit()

    @Slot(int)
    def toggleFlag(self, word_index: int) -> None:
        if self.script is None or not 0 <= word_index < len(self.script.words):
            return
        key = self.script.words[word_index].key
        flagged = not self._flagged(key)
        if self.lexicon.path:
            self.lexicon.set_flag(key, flagged)
        self.history.flag(key, flagged)
        self.history.save()
        self._rebuild_paragraphs()
        self.notice.emit("info", f"“{key}” {'flagged' if flagged else 'unflagged'}")

    @Slot()
    def flagCurrent(self) -> None:
        if self._coach.get("flagged"):
            for entry in self._coach["flagged"]:
                if entry.get("word", -1) >= 0:
                    self.toggleFlag(entry["word"])
                    return
        self.toggleFlag(self._current_word + 1)

    @Slot(str)
    def listenTo(self, text: str) -> None:
        key = text.strip().lower().strip(".,;:!?\"'()[]")
        self.processes.send_engine({"type": "tts", "text": text, "slow": True, "ipa": self.lexicon.word_ipa(key)})

    @staticmethod
    def _layout_named(name) -> str:
        return name if name in LAYOUTS else "full"

    @Slot(str)
    def setLayout(self, layout: str) -> None:
        if layout not in LAYOUTS:
            return
        self._layout = layout
        self._panels = dict(LAYOUTS[layout])
        if self.config["general"].get("layout") != layout:
            self.config["general"]["layout"] = layout
            config_module.save(self.config)
        self.layoutChanged.emit()

    @Slot(int)
    def cycleLayout(self, delta: int) -> None:
        self.setLayout(LAYOUT_ORDER[(LAYOUT_ORDER.index(self._layout) + delta) % len(LAYOUT_ORDER)])


    @Slot()
    def cycleDisplayMode(self) -> None:
        index = DISPLAY_MODES.index(self._display_mode) if self._display_mode in DISPLAY_MODES else 0
        self._display_mode = DISPLAY_MODES[(index + 1) % len(DISPLAY_MODES)]
        self.setSetting("prompter", "mode", self._display_mode)
        self.notice.emit("info", f"Prompter: {self._display_mode}")
        self.layoutChanged.emit()

    @Slot(str, str, "QVariant")
    def setSetting(self, section: str, key: str, value) -> None:
        if section == "phone" and key not in self.PHONE_GLOBAL_KEYS and self._active_serial:
            phones = self.config["phone"].setdefault("phones", {})
            if self._phone_config().get(key) == value:
                return
            phones.setdefault(self._active_serial, {})[key] = value
            config_module.save(self.config)
            self.settingsChanged.emit()
            if not self._recording:
                self._restart_phone_preview()
            return
        if section not in self.config:
            self.config[section] = {}
        if self.config[section].get(key) == value:
            return
        self.config[section][key] = value
        if section == "coach" and key == "threshold" and float(self.config["coach"].get("require") or 0) > float(value):
            # Requiring a retake above the warning level would sink takes for words that aren't even warned about.
            self.config["coach"]["require"] = value
        config_module.save(self.config)
        self.settingsChanged.emit()
        if section == "phone" and key == "serial":
            self._resolve_active_phone()
            self.phoneCamerasChanged.emit()
            self.settingsChanged.emit()
        if section == "phone" and not self._recording:
            self._restart_phone_preview()
        if section == "camera" and key == "source":
            self._phoneUpdate.emit()
        if section == "guides":
            self._rebuild_paragraphs()
        elif section == "prompter" and key == "mode":
            self._display_mode = value
            self.layoutChanged.emit()
        elif section == "audio":
            audio = self.config["audio"]
            self.processes.send_recorder({"type": "open", "source": audio.get("input", "default"), "channels": audio.get("channels", "mix"), "sample_rate": audio.get("sample_rate", 0)})
        elif section in ("engines", "voice") or (section == "general" and key in ("script_language", "ui_language")):
            self._refresh_model_jobs()
            self._engine_pending = True
            self.enginePendingChanged.emit()
        elif section == "general" and key == "native_language" and self.script_path:
            self._load_script(self.script_path)

    @Slot()
    def restartEngine(self) -> None:
        if self._recording:
            self.notice.emit("error", "Stop the recording before restarting the engine")
            return
        self._start_engine()
        self._engine_pending = False
        self.enginePendingChanged.emit()

    @Slot()
    def runPreflight(self) -> None:
        if self.script is None:
            self._preflight = []
            self.preflightChanged.emit()
            return
        pack = packs.get(self.config["general"]["script_language"])
        wake = self.config["voice"].get("wake_word") or packs.get(self._engine_settings.get("commands_language", pack.code)).wake_word
        errors = {role: info.get("detail", "") for role, info in self._engines.items() if info.get("state") == "error"}
        issues = preflight.check(self.script, self.guides, pack, wake, engine_settings.missing_models(self.config), errors)
        vram_needed, _ = estimate_preset(self._engine_settings)
        snapshot = self._resources.get("_snapshot")
        if snapshot is not None and vram_needed and snapshot.gpu.memory_total_mb:
            free = snapshot.gpu.memory_total_mb - (snapshot.gpu.memory_used_mb or 0)
            if free < vram_needed:
                holders = ", ".join(f"{p.name} ({p.memory_mb / 1024:.1f} GB)" for p in snapshot.gpu.processes[:3])
                issues.insert(0, preflight.Issue(preflight.WARNING, "resources", f"This preset needs about {vram_needed / 1024:.1f} GB of VRAM but only {free / 1024:.1f} GB is free. Held by: {holders}. Pick a lighter preset in Settings."))
        self._preflight = [i.as_dict() for i in issues]
        self.preflightChanged.emit()

    @Slot()
    def refreshDevices(self) -> None:
        self.processes.send_recorder({"type": "sources"})

    def _video_cameras(self) -> list[dict]:
        """The cameras to choose from: every video device but the phone's virtual camera and
        infrared sensors. A laptop's face-login sensor shows up as a second camera with the same
        name that only gives a grey picture."""
        grey = {QVideoFrameFormat.PixelFormat.Format_Y8, QVideoFrameFormat.PixelFormat.Format_Y16}
        cameras = []
        for device in QMediaDevices.videoInputs():
            formats = device.videoFormats()
            if device.description() == phone_video.LOOPBACK_LABEL or (formats and all(f.pixelFormat() in grey for f in formats)):
                continue
            cameras.append({"id": bytes(device.id()).decode(), "description": device.description(), "default": device.isDefault()})
        names = [camera["description"] for camera in cameras]
        for camera in cameras:
            if names.count(camera["description"]) > 1:
                camera["description"] += f" ({camera['id']})"
        return cameras

    @Slot(QObject, QObject)
    def forwardFrames(self, source_output: QObject, target_output: QObject) -> None:
        source = source_output.property("videoSink")
        target = target_output.property("videoSink")
        if not isinstance(source, QVideoSink) or not isinstance(target, QVideoSink):
            return
        source.videoFrameChanged.connect(lambda frame, sink=target: sink.setVideoFrame(frame))
        self._frame_links = getattr(self, "_frame_links", []) + [(source, target)]

    def _refresh_models(self) -> None:
        rows = []
        for spec in model_registry.REGISTRY.values():
            requirements = all(config_module.has_module(name) for name in spec.requires)
            rows.append({
                "id": spec.id, "title": spec.title, "role": spec.role, "license": spec.license,
                "size": spec.size_mb, "installed": spec.installed(), "progress": -1.0,
                "note": spec.note if requirements else "needs " + ", ".join(spec.requires),
                "available": requirements,
            })
        self.models.set_items(rows)
        self._refresh_model_jobs()

    def _refresh_model_jobs(self) -> None:
        try:
            self.model_jobs.set_items(modeljobs.rows(self.config, self._download_progress))
        except Exception as error:
            self.notice.emit("error", f"Models: {error}")

    @Slot(str, str)
    def selectJobOption(self, job: str, value: str) -> None:
        if modeljobs.choice(self.config, job) == value:
            return
        modeljobs.apply_choice(self.config, job, value)
        config_module.save(self.config)
        self.settingsChanged.emit()
        self._refresh_model_jobs()
        self._engine_pending = True
        self.enginePendingChanged.emit()

    @Slot(str)
    def downloadModel(self, model_id: str) -> None:
        spec = model_registry.get(model_id)

        def progress(done: int, total: int):
            self._downloadProgress.emit(model_id, done / total if total else 0.0, "")

        def work():
            try:
                model_registry.Download(spec, progress).run()
                self._downloadProgress.emit(model_id, 2.0, "")
            except Exception as error:
                self._downloadProgress.emit(model_id, -2.0, str(error))

        threading.Thread(target=work, daemon=True).start()

    def _on_download_progress(self, model_id: str, fraction: float, error: str) -> None:
        if 0 <= fraction <= 1:
            self._download_progress[model_id] = fraction
            for row_index, row in enumerate(self.model_jobs.items()):
                if row["model"] == model_id:
                    self.model_jobs.update(row_index, {"progress": fraction})
        else:
            self._download_progress.pop(model_id, None)
            self._refresh_model_jobs()
        rows = self.models.items()
        for row_index, row in enumerate(rows):
            if row["id"] == model_id:
                if fraction == 2.0:
                    self.models.update(row_index, {"installed": True, "progress": -1.0})
                    self.notice.emit("info", f"Installed {row['title']}. Restart the engine to use it.")
                elif fraction == -2.0:
                    self.models.update(row_index, {"progress": -1.0})
                    self.notice.emit("error", f"Download failed: {error}")
                else:
                    self.models.update(row_index, {"progress": fraction})

    @Slot(str)
    def removeModel(self, model_id: str) -> None:
        model_registry.remove(model_id)
        self._refresh_models()

    def _sample_resources(self) -> None:
        self.monitor.watch(self.processes.pids())
        snapshot = self.monitor.sample()
        summary = snapshot.summary()
        summary["disk_minutes"] = round(self.monitor.disk_minutes(snapshot))
        summary["processes"] = snapshot.processes
        summary["gpu_name"] = snapshot.gpu.name
        summary["gpu_processes"] = [{"name": p.name, "pid": p.pid, "memory_mb": round(p.memory_mb)} for p in snapshot.gpu.processes]
        summary["temperature"] = snapshot.gpu.temperature
        summary["encoder"] = snapshot.gpu.encoder
        summary["disk_write"] = round(snapshot.disk_write_mbps, 2)
        summary["latency"] = {k: round(v, 2) for k, v in self._engine_metrics.get("latency", {}).items()}
        summary["queue"] = self._engine_metrics.get("queue", 0)
        summary["ram_available_gb"] = round(snapshot.ram_available_mb / 1024, 1)
        summary["ram_pct"] = round(100 * snapshot.ram_used_mb / max(1.0, snapshot.ram_total_mb))
        summary["cpu_threads"] = os.cpu_count() or 0
        gpu = snapshot.gpu
        summary["vram_pct"] = None if gpu.memory_used_mb is None or not gpu.memory_total_mb else round(100 * gpu.memory_used_mb / gpu.memory_total_mb)
        summary["_snapshot"] = snapshot
        self._resources = summary
        self.resourcesChanged.emit()
        if self.resource_log is not None:
            self.resource_log.write(self._time, snapshot, self._engine_metrics)

    @Slot(result=bool)
    def canQuit(self) -> bool:
        return self._closing or not self._recording

    @Slot()
    def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._recording:
            self.stop()
        self.editor.save()
        if self.pedal:
            self.pedal.stop()
        self.phone_frames.stop()
        if self.phone_preview is not None:
            self.phone_preview.stop()
            self.phone_preview = None
        self.processes.shutdown()

    @Slot()
    def openProjectsFolder(self) -> None:
        folder = Path(self.config["general"]["projects_dir"]).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    @Slot()
    def clearPracticeHistory(self) -> None:
        self.history.clear()
        self.history.save()
        self._rebuild_paragraphs()
        self.notice.emit("info", "Coach history cleared")

    @Slot(result="QVariant")
    def drillList(self):
        return [{"word": w, "misses": m, "attempts": a} for w, m, a in self.history.drill_list()[:50]]

    def _page_get(self):
        return self._page

    @Slot(str)
    def removeRecentProject(self, path: str) -> None:
        self.config["general"]["recent_projects"] = [p for p in self.config["general"].get("recent_projects", []) if p != path]
        config_module.save(self.config)
        self.recentChanged.emit()

    @Slot()
    def clearRecentProjects(self) -> None:
        self.config["general"]["recent_projects"] = []
        config_module.save(self.config)
        self.recentChanged.emit()

    def _recent_projects(self) -> list[dict]:
        rows = []
        for path in self.config["general"].get("recent_projects", []):
            try:
                project = Project.load(Path(path))
            except Exception:
                continue
            items = project.items
            rows.append({
                "path": path, "title": project.title,
                "scripts": len(items),
                "duration": sum(i.duration for i in items),
            })
            project.close()
        return rows

    def _effective_settings(self) -> dict:
        """The settings the UI shows, with the active phone's own settings filled in."""
        if self._settings_cache is not None:
            return self._settings_cache
        merged = dict(self.config)
        merged["phone"] = self._phone_config()
        self._settings_cache = merged
        return merged

    def _card(self) -> dict:
        if self.script is None:
            return {}
        rows = {s["index"]: s for row in self.paragraphs.items() for s in row["sentences"]}
        current = self._current_sentence
        following = self.script.next_sentence(current)
        previous = self.script.previous_sentence(current)
        return {
            "current": rows.get(current),
            "next": rows.get(following) if following is not None else None,
            "previous": rows.get(previous) if previous is not None else None,
        }

    def _sentence_progress(self) -> dict:
        if self.script is None:
            return {"index": 0, "total": 0}
        trackable = [s.index for s in self.script.sentences if s.trackable or s.kind == ADLIB]
        position = trackable.index(self._current_sentence) + 1 if self._current_sentence in trackable else 0
        return {"index": position, "total": len(trackable)}

    page = Property(str, _page_get, notify=pageChanged)
    state = Property(str, lambda self: self._state, notify=stateChanged)
    recording = Property(bool, lambda self: self._recording, notify=stateChanged)
    rehearsal = Property(bool, lambda self: self._rehearsal, notify=stateChanged)
    sessionTime = Property(float, lambda self: self._time, notify=timeChanged)
    hasScript = Property(bool, lambda self: self.script is not None, notify=scriptChanged)
    scriptTitle = Property(str, lambda self: self.script.title if self.script else "", notify=scriptChanged)
    paragraphModel = Property(QObject, lambda self: self.paragraphs, constant=True)
    takesModel = Property(QObject, lambda self: self.takes, constant=True)
    modelsModel = Property(QObject, lambda self: self.models, constant=True)
    modelJobs = Property(QObject, lambda self: self.model_jobs, constant=True)

    def _voice_commands(self) -> dict:
        settings = getattr(self, "_engine_settings", None) or engine_settings.build(self.config, check_gpu=False)
        try:
            pack = packs.get(settings.get("commands_language") or self.config["general"]["script_language"])
        except KeyError:
            return {"enabled": False, "wake": "", "actions": {}, "say": []}
        return {
            "enabled": bool(self.config["voice"].get("enabled", True)),
            "wake": settings.get("wake_word") or pack.wake_word,
            "actions": {action: list(phrases) for action, phrases in pack.commands.items()},
            "say": list(pack.say_prefixes),
        }

    voiceCommands = Property("QVariant", _voice_commands, notify=settingsChanged)
    enginePending = Property(bool, lambda self: self._engine_pending, notify=enginePendingChanged)
    finishing = Property(str, lambda self: self._finishing, notify=finishingChanged)
    startingVideo = Property(str, lambda self: self._starting_video, notify=startingVideoChanged)
    opening = Property(str, lambda self: self._opening, notify=openingChanged)
    currentSentence = Property(int, lambda self: self._current_sentence, notify=positionChanged)
    currentWord = Property(int, lambda self: self._current_word, notify=positionChanged)
    currentParagraph = Property(int, lambda self: self.script.sentences[self._current_sentence].paragraph if self.script and self._current_sentence < len(self.script.sentences) else 0, notify=positionChanged)
    progress = Property("QVariant", _sentence_progress, notify=positionChanged)
    card = Property("QVariant", _card, notify=positionChanged)
    level = Property("QVariant", lambda self: self._level, notify=levelChanged)
    engines = Property("QVariant", lambda self: self._engines, notify=engineChanged)
    resources = Property("QVariant", lambda self: {k: v for k, v in self._resources.items() if not k.startswith("_")}, notify=resourcesChanged)
    settings = Property("QVariant", _effective_settings, notify=settingsChanged)
    layout = Property(str, lambda self: self._layout, notify=layoutChanged)
    panels = Property("QVariant", lambda self: self._panels, notify=layoutChanged)
    displayMode = Property(str, lambda self: self._display_mode, notify=layoutChanged)
    coach = Property("QVariant", lambda self: self._coach, notify=coachChanged)
    review = Property("QVariant", lambda self: self._review, notify=coachChanged)
    drill = Property("QVariant", lambda self: self._drill, notify=drillChanged)
    wordMarks = Property("QVariant", lambda self: self._word_marks, notify=drillChanged)
    preflightIssues = Property("QVariant", lambda self: self._preflight, notify=preflightChanged)
    audioSources = Property("QVariant", lambda self: self._sources, notify=devicesChanged)
    videoCameras = Property("QVariant", _video_cameras, notify=devicesChanged)
    recentProjects = Property("QVariant", _recent_projects, notify=recentChanged)
    hasProject = Property(bool, lambda self: self.project is not None, notify=projectChanged)
    projectTitle = Property(str, lambda self: self.project.title if self.project else "", notify=projectChanged)
    itemTitle = Property(str, lambda self: self.item.title if self.item else "", notify=itemChanged)
    projectPath = Property(str, lambda self: str(self.project.path) if self.project else "", notify=projectChanged)
    explorerVisible = Property(bool, lambda self: self._explorer_visible, notify=projectChanged)
    explorerModel = Property(QObject, lambda self: self.explorer, constant=True)
    pickupPending = Property(bool, lambda self: bool(self._pickup) and not self._recording, notify=coachChanged)
    phonePreviewActive = Property(bool, lambda self: self.phone_frames.active, notify=phonePreviewChanged)
    cameraSource = Property(str, lambda self: self.config["camera"].get("source", "none"), notify=settingsChanged)
    phoneMode = Property(bool, lambda self: self._phone_mode(), notify=settingsChanged)
    phonePortrait = Property(bool, lambda self: self._phone_mode() and phone_video.portrait(self._phone_config()), notify=settingsChanged)
    phoneCameras = Property("QVariant", _camera_rows, notify=phoneCamerasChanged)
    phoneDevices = Property("QVariant", _phone_rows, notify=phoneCamerasChanged)
    detectingPhoneCameras = Property(bool, lambda self: self._detecting, notify=phoneCamerasChanged)
    phoneLoopback = Property(bool, lambda self: phone_video.loopback_device() is not None, notify=settingsChanged)
    cameraAllowed = Property(bool, lambda self: not os.environ.get("RETAKE_NO_CAMERA"), constant=True)
    languages = Property("QVariant", lambda self: [{"code": p.code, "name": p.name} for p in packs.all_packs().values()], constant=True)


class _Listener:
    def __init__(self, controller: Controller):
        self.controller = controller

    def state_changed(self, state):
        self.controller.state_changed(state)

    def position_changed(self, sentence, word):
        self.controller.position_changed(sentence, word)

    def sentence_changed(self, sentence):
        self.controller.sentence_changed(sentence)

    def takes_changed(self):
        self.controller.takes_changed()

    def coach_feedback(self, take, flagged, deviations):
        self.controller.coach_feedback(take, flagged, deviations)

    def notice(self, kind, text):
        self.controller.notice_from_session(kind, text)

    def request(self, message):
        self.controller.request(message)

    def camera(self, layout):
        self.controller.camera(layout)

    def scene(self, name):
        self.controller.scene(name)

    def review_changed(self, queue, index):
        self.controller.review_changed(queue, index)

    def drill_changed(self, drill):
        self.controller.drill_changed(drill)

    def stop_requested(self):
        QTimer.singleShot(0, self.controller.stop)

    def marks_changed(self, red, warned):
        self.controller.marks_changed(red, warned)
