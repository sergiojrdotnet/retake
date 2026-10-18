from __future__ import annotations

import os
import queue
import threading
import time
import traceback
import warnings
from multiprocessing.connection import Client, Connection, wait
from pathlib import Path

import numpy as np

from ..child import exit_quietly
from .audio import RATE, AudioHistory, SpeechTimeline
from .commands import CommandGate, TranscriptCommands
from .log import OutputLog, log
from .vad import EnergyVad

UTTERANCE_GAP = 0.8
WHISPER_INTERVAL = 0.6
MAX_UTTERANCE = 24.0
COMMAND_ISOLATION = 0.45
MAX_TRACKING_LAG = 3.0
WORD_MARGIN_DB = 15.0


class Worker:
    """Runs one kind of heavy job in order on its own thread."""

    def __init__(self, name: str):
        self.jobs: queue.Queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)
        self.thread.start()

    def submit(self, job) -> None:
        self.jobs.put(job)

    def pending(self) -> int:
        return self.jobs.qsize()

    def _run(self) -> None:
        while True:
            job = self.jobs.get()
            if job is None:
                return
            try:
                job()
            except Exception:
                traceback.print_exc()

    def stop(self) -> None:
        self.jobs.put(None)


class Engine:
    def __init__(self, control: Connection, audio_address: str, authkey: bytes, settings: dict):
        self.control = control
        self.audio = self._connect(audio_address, authkey)
        self.settings = settings
        self.send_lock = threading.Lock()
        self.history = AudioHistory()
        self.timeline = SpeechTimeline()
        self.running = True
        self.status: dict[str, dict] = {}
        self.vad = None
        # Silero often rates a word said on its own as unlikely speech, so drill tries are found by
        # loudness instead: a word stands well above the room's noise.
        self.word_vad = EnergyVad(WORD_MARGIN_DB)
        self.tracker = None
        self.whisper = None
        self.transcript_commands: TranscriptCommands | None = None
        self.command_gate = CommandGate()
        self.commands = None
        self.scorer = None
        self.voice = None
        # Scoring a sentence can take seconds; on a worker of its own it never holds up following.
        self.tracking_jobs = Worker("tracking")
        self.scoring_jobs = Worker("scoring")
        self.vad_queue: queue.Queue = queue.Queue()
        self.track_queue: queue.Queue = queue.Queue()
        self.command_queue: queue.Queue = queue.Queue()
        self.context_text = ""
        self.utterance_start: float | None = None
        self.last_decode = 0.0
        self.decoding = False
        # Whisper is prompted with the sentence being read, or with the last words heard for an ad-lib.
        self.recent_prompt = ""
        self.latency: dict[str, float] = {}
        self.reported_progress = 0.0
        self.listening = False
        # Between recordings, only voice commands are listened for ("retake, start recording").
        self.commands_only = False

    @staticmethod
    def _connect(address: str, authkey: bytes) -> Connection:
        for _ in range(100):
            try:
                return Client(address, family="AF_UNIX", authkey=authkey)
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.1)
        raise ConnectionError(f"recorder audio socket not available: {address}")

    def send(self, message: dict) -> None:
        with self.send_lock:
            try:
                self.control.send(message)
            except (BrokenPipeError, OSError):
                self.running = False

    def report(self, role: str, name: str, state: str, detail: str = "") -> None:
        self.status[role] = {"engine": name, "state": state, "detail": detail}
        self.send({"type": "status", "engines": self.status})

    def load(self) -> None:
        settings = self.settings
        log(f"starting: device {settings['device']}, Whisper on {settings.get('whisper_device', settings['device'])}, "
            f"{settings['threads']} CPU threads, {_gpu_summary()}")
        self._load("vad", settings["vad"], self._load_vad)
        self._load("tracking", settings["tracking"], self._load_tracking)
        if settings.get("commands"):
            self._load("commands", "vosk", self._load_commands)
        self._load("scorer", settings["scorer"], self._load_scorer)
        self._load("tts", settings["tts"], self._load_tts)

    def _load(self, role: str, name: str, loader) -> None:
        self.report(role, name, "loading")
        started = time.monotonic()
        try:
            detail = loader() or ""
            loaded = getattr(self, "_loaded_name", name)
            self.report(role, loaded, "ready", detail)
            log(f"{role}: {loaded} ready in {time.monotonic() - started:.1f} s" + (f" ({detail})" if detail else ""))
        except Exception as error:
            self.report(role, name, "error", f"{type(error).__name__}: {error}")
            log(f"{role}: {name} failed after {time.monotonic() - started:.1f} s")
            traceback.print_exc()

    def _load_vad(self):
        from .vad import EnergyVad, SileroVad

        self._loaded_name = self.settings["vad"]
        if self.settings["vad"] == "silero":
            self.vad = SileroVad(self.settings["silero_model"])
        else:
            self.vad = EnergyVad()

    def _load_tracking(self):
        self._loaded_name = self.settings["tracking"]
        if self.settings["tracking"] == "whisper":
            from .whisper_engine import WhisperTranscriber

            device = self.settings.get("whisper_device", self.settings["device"])
            try:
                self.whisper = WhisperTranscriber(
                    self.settings.get("whisper_source", self.settings["whisper_model"]),
                    self.settings["whisper_root"],
                    device,
                    self.settings["whisper_language"],
                    self.settings["threads"],
                )
                return f"{self.settings['whisper_model']} on {self.whisper.device}"
            except Exception as error:
                # Whisper on the CPU can't keep up with live reading, so a GPU failure falls back to Vosk.
                if device == "cpu" or not self.settings.get("tracking_installed"):
                    raise
                self.whisper = None
                reason = f"Whisper couldn't use the GPU ({type(error).__name__}: {error}); using Vosk"
                traceback.print_exc()
        else:
            reason = ""
        from .vosk_engine import VoskTracker

        self._loaded_name = "vosk"
        self.tracker = VoskTracker(self.settings["tracking_model"])
        return reason

    def _load_commands(self):
        from ..languages import packs
        from .vosk_engine import VoskCommands

        self._loaded_name = "vosk"
        self.commands = VoskCommands(
            self.settings["commands_model"], packs.get(self.settings["commands_language"]), self.settings.get("wake_word") or None,
            aliases=self.settings.get("wake_aliases"),
        )
        self.transcript_commands = TranscriptCommands(
            packs.get(self.settings["commands_language"]), self.commands.wake, self.settings.get("wake_aliases"),
        )
        if self.commands.missing:
            return "not in vocabulary: " + ", ".join(self.commands.missing)
        return f"wake word: {self.commands.wake}"

    def _load_scorer(self):
        self._loaded_name = self.settings["scorer"]
        if self.settings["scorer"] != "wav2vec2":
            return "word-level check only"
        from ..languages import packs
        from .scorer import PhonemeScorer

        pack = packs.get(self.settings["script_language"])
        device = self.settings["device"] if self.settings["device"] != "auto" else "cpu"
        self.scorer = PhonemeScorer(
            self.settings["scorer_model"],
            pack.espeak_voice,
            device=device,
            half=device == "cuda",
            threads=self.settings["threads"],
            function_words=pack.function_words,
            use_cmudict=pack.lexicon == "cmudict",
        )
        return device

    def _load_tts(self):
        from ..languages import packs
        from .tts import EspeakVoice, PiperVoice

        self._loaded_name = self.settings["tts"]
        if self.settings["tts"] == "piper":
            self.voice = PiperVoice(self.settings["piper_model"])
        else:
            self.voice = EspeakVoice(packs.get(self.settings["script_language"]).espeak_voice)

    def run(self) -> None:
        threads = [
            threading.Thread(target=self._vad_loop, name="vad", daemon=True),
            threading.Thread(target=self._track_loop, name="track", daemon=True),
            threading.Thread(target=self._command_loop, name="commands", daemon=True),
            threading.Thread(target=self._metrics_loop, name="metrics", daemon=True),
        ]
        loader = threading.Thread(target=self.load, name="load", daemon=True)
        loader.start()
        for thread in threads:
            thread.start()
        while self.running:
            ready = wait([self.control, self.audio], timeout=0.5)
            for connection in ready:
                try:
                    message = connection.recv()
                except (EOFError, OSError):
                    self.running = False
                    break
                if connection is self.audio:
                    self._on_audio(message)
                else:
                    self._on_control(message)
        self.tracking_jobs.stop()
        self.scoring_jobs.stop()

    def _on_audio(self, message) -> None:
        start_sample, payload = message
        if start_sample == "reset":
            self._reset(int(payload))
            return
        samples = np.frombuffer(payload, dtype=np.int16)
        self.history.append(start_sample, samples)
        if not self.listening and not self.commands_only:
            return
        arrived = time.monotonic()
        self.vad_queue.put((start_sample, samples, arrived))
        if self.listening:
            self.track_queue.put((start_sample, samples, arrived))
        if self.settings.get("commands"):
            self.command_queue.put((start_sample, samples, arrived))

    def _on_control(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "listen":
            self.listening = bool(message.get("active"))
            self.commands_only = bool(message.get("commands")) and not self.listening
            if not self.listening:
                self.utterance_start = None
                for pending in (self.vad_queue, self.track_queue, self.command_queue):
                    while not pending.empty():
                        try:
                            pending.get_nowait()
                        except queue.Empty:
                            break
        elif kind == "context":
            self.context_text = message.get("text", "")
            if self.commands is not None:
                self.commands.set_words(message.get("words", []))
        elif kind == "score":
            self.scoring_jobs.submit(lambda m=message: self._score(m))
        elif kind == "tts":
            threading.Thread(target=self._tts, args=(message,), daemon=True).start()
        elif kind == "stop":
            self.running = False

    def _reset(self, start: int) -> None:
        for pending in (self.vad_queue, self.track_queue, self.command_queue):
            while not pending.empty():
                try:
                    pending.get_nowait()
                except queue.Empty:
                    break
            pending.put(("reset", start, None))
        self.history.reset()
        self.timeline.reset()
        self.utterance_start = None
        self.reported_progress = start / RATE
        self.send({"type": "reset", "start_sample": start})

    @staticmethod
    def _batch(source: queue.Queue, first, limit: int = 40) -> list:
        batches: list = []
        current: list = []

        def flush():
            if current:
                start = current[0][0]
                samples = np.concatenate([c[1] for c in current])
                batches.append((start, samples, current[0][2]))
                current.clear()

        item = first
        while item is not None:
            if item[0] == "reset":
                flush()
                batches.append(item)
            else:
                if current and current[-1][0] + len(current[-1][1]) != item[0]:
                    flush()
                current.append(item)
            if len(current) >= limit:
                break
            try:
                item = source.get_nowait()
            except queue.Empty:
                item = None
        flush()
        return batches

    def _vad_loop(self) -> None:
        while self.running:
            try:
                first = self.vad_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            for start, samples, arrived in self._batch(self.vad_queue, first):
                if start == "reset":
                    if self.vad:
                        self.vad.reset(samples)
                    self.word_vad.reset(samples)
                    continue
                for speech, at in self.word_vad.process(start, samples):
                    self.send({"type": "word", "speech": speech, "time": at})
                if self.vad is None:
                    continue
                for speech, at in self.vad.process(start, samples):
                    if speech:
                        self.timeline.speech_started(at)
                        if self.utterance_start is None and self.listening:
                            self.utterance_start = at
                    else:
                        self.timeline.speech_ended(at)
                    self.send({"type": "vad", "speech": speech, "time": at})
                self.latency["vad"] = time.monotonic() - arrived

    def _track_loop(self) -> None:
        while self.running:
            try:
                first = self.track_queue.get(timeout=0.2)
            except queue.Empty:
                first = None
            if first is None:
                if self.whisper is not None:
                    self._schedule_whisper()
                continue
            if first[0] != "reset" and self.tracker is not None and time.monotonic() - first[2] > self.settings.get("max_tracking_lag", MAX_TRACKING_LAG):
                first = self._skip_ahead(first)
            for start, samples, arrived in self._batch(self.track_queue, first, limit=12):
                if start == "reset":
                    if self.tracker:
                        self.tracker.reset(samples)
                    continue
                if self.tracker is not None:
                    for event in self.tracker.feed(start, samples):
                        self.send(event)
                    self.latency["tracking"] = time.monotonic() - arrived
                    processed = (start + len(samples)) / RATE
                    if processed - self.reported_progress >= 0.2:
                        self.reported_progress = processed
                        self.send({"type": "progress", "time": processed})
                elif self.whisper is not None:
                    self._schedule_whisper()

    def _skip_ahead(self, first):
        newest = first
        while True:
            try:
                item = self.track_queue.get_nowait()
            except queue.Empty:
                break
            if item[0] == "reset":
                return item
            newest = item
        skipped_from = first[0] / RATE
        log(f"following fell behind; skipped {newest[0] / RATE - skipped_from:.1f} s of audio")
        self.tracker.reset(newest[0])
        self.send({"type": "gap", "from": skipped_from, "to": newest[0] / RATE})
        return newest

    def _schedule_whisper(self) -> None:
        if self.decoding or self.utterance_start is None:
            return
        now = self.history.duration
        speaking = self.timeline.speaking()
        last_end = self.timeline.last_end_before(now) or now
        utterance_over = not speaking and now - last_end >= UTTERANCE_GAP
        too_long = now - self.utterance_start >= MAX_UTTERANCE
        due = now - self.last_decode >= WHISPER_INTERVAL
        if not (utterance_over or too_long or (speaking and due)):
            return
        start = self.utterance_start
        end = now
        final = utterance_over or too_long
        if final:
            self.utterance_start = None if utterance_over else now
        self.decoding = True
        self.last_decode = now
        self.tracking_jobs.submit(lambda: self._decode(start, end, final))

    def _decode(self, start: float, end: float, final: bool) -> None:
        try:
            if self.timeline.speech_between(start, end) < 0.25:
                return
            began = time.monotonic()
            window_start = max(0.0, start - 0.2)
            audio = self.history.slice(window_start, end)
            prompt = self.context_text or self.recent_prompt
            words = self.whisper.transcribe(audio, window_start, prompt)
            words = [w for w in words if self.timeline.speech_between(w["start"] - 0.1, w["end"] + 0.1) > 0]
            self.send({"type": "words", "final": final, "replace_from": window_start, "words": words})
            if self.transcript_commands is not None:
                for event in self.transcript_commands.find(words):
                    if self.command_gate.admit(event):
                        self.send(event)
            self.send({"type": "progress", "time": end})
            if final and words:
                self.recent_prompt = " ".join(w["text"] for w in words)[-200:]
            self.latency["tracking"] = time.monotonic() - began
        finally:
            self.decoding = False

    def _command_loop(self) -> None:
        while self.running:
            try:
                first = self.command_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            for start, samples, arrived in self._batch(self.command_queue, first, limit=12):
                if start == "reset":
                    if self.commands:
                        self.commands.reset(samples)
                    continue
                if self.commands is None:
                    continue
                for event in self.commands.feed(start, samples):
                    before = self.timeline.speech_between(event["start"] - COMMAND_ISOLATION - 0.4, event["start"] - 0.08)
                    if before > 0.15 or not self.command_gate.admit(event):
                        continue
                    self.send(event)
                self.latency["commands"] = time.monotonic() - arrived

    def _score(self, message: dict) -> None:
        request = message["request"]
        if self.scorer is None:
            self.send({"type": "score", "request": request, "error": "unavailable"})
            return
        try:
            audio = self.history.slice(message["start"], message["end"])
            if len(audio) < RATE * 0.2:
                self.send({"type": "score", "request": request, "error": "too short"})
                return
            words = self.scorer.score(audio, message["words"])
            for word in words:
                if word.get("start") is not None:
                    word["start"] += message["start"]
                    word["end"] += message["start"]
            self.latency["scorer"] = self.scorer.last_seconds
            self.send({"type": "score", "request": request, "take": message.get("take"), "words": words})
        except Exception as error:
            traceback.print_exc()
            self.send({"type": "score", "request": request, "error": str(error)})

    def _tts(self, message: dict) -> None:
        if self.voice is None:
            return
        try:
            audio, rate = self.voice.synthesize(message["text"], message.get("slow", False), message.get("ipa"))
            self.send({"type": "tts", "text": message["text"], "rate": rate, "audio": audio.astype(np.float32).tobytes()})
        except Exception as error:
            self.send({"type": "tts", "text": message["text"], "error": str(error)})

    def _metrics_loop(self) -> None:
        while self.running:
            time.sleep(1.0)
            self.send({
                "type": "metrics",
                "latency": dict(self.latency),
                "queue": self.tracking_jobs.pending() + self.scoring_jobs.pending(),
                "audio": self.history.duration,
                "pid": os.getpid(),
            })


def _gpu_summary() -> str:
    try:
        import torch
    except ImportError:
        return "no PyTorch"
    if not torch.cuda.is_available():
        return f"PyTorch {torch.__version__} without a GPU"
    return f"PyTorch {torch.__version__} on {torch.cuda.get_device_name(0)}"


def engine_main(control: Connection, audio_address: str, authkey: bytes, settings: dict) -> None:
    os.environ.setdefault("OMP_NUM_THREADS", str(settings.get("threads", 4)))
    if settings.get("device") == "cpu" and settings.get("whisper_device", "cpu") == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    warnings.filterwarnings("ignore", message=r"`torch\.jit\.load` is not supported", category=FutureWarning)
    output = OutputLog(Path(settings["log_file"])) if settings.get("log_file") else None
    crashed = False
    try:
        Engine(control, audio_address, authkey, settings).run()
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
        crashed = True
    if output is not None:
        output.close()
    if crashed:
        os._exit(1)
    exit_quietly()
