"""End-to-end engine check with synthesized speech (CPU only).

Run: CUDA_VISIBLE_DEVICES= .venv/bin/python tests/integration_engine.py
"""
from __future__ import annotations

import multiprocessing
import os
import secrets
import sys
import time
from multiprocessing.connection import Listener

import numpy as np
import soxr

from retake import config as config_module
from retake.engine import settings as engine_settings
from retake.engine.process import engine_main
from retake.languages import packs
from retake.phonetics import espeak
from retake.script.parser import parse
from retake.session.session import Session, SessionSettings
from retake.session.takes import TakeLog

SCRIPT = """
# Demo

We flush the cache to disk. Then we measure the latency of every request.

Finally we compare the results with the previous benchmark.
"""

UTTERANCES = [
    "we flush the cache to disk",
    "then we measure the latency",
    "retake again",
    "then we measure the latency of every request",
    "finally we compare the results with the previous benchmark",
]


class Listener_:
    def __init__(self):
        self.events = []

    def __getattr__(self, name):
        def handler(*args):
            self.events.append((name, args))
            if name in ("notice", "coach_feedback"):
                print("  ->", name, args[:2] if name == "notice" else (args[0].sentence, [f["text"] for f in args[1]], args[2]))
        return handler


def synth(text: str) -> np.ndarray:
    audio, rate = espeak.synthesize(text, "en-us", 150)
    audio = soxr.resample(audio, rate, 16000)
    return (np.clip(audio, -1, 1) * 30000).astype(np.int16)


def main() -> int:
    config = config_module.load()
    config["engines"].update({"device": "cpu", "vad": "silero", "tracking": "vosk", "scorer": "wav2vec2", "tts": "espeak"})
    settings = engine_settings.build(config, check_gpu=False)
    settings["max_tracking_lag"] = 1e9
    print("settings:", {k: settings[k] for k in ("vad", "tracking", "scorer", "tts", "commands", "wake_word")})
    address = f"/tmp/claude-1000/retake-test-{os.getpid()}.sock"
    authkey = secrets.token_bytes(8)
    listener = Listener(address, family="AF_UNIX", authkey=authkey)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=engine_main, args=(child, address, authkey, settings), daemon=True)
    process.start()
    audio_conn = listener.accept()
    deadline = time.time() + 120
    status = {}
    while time.time() < deadline:
        if parent.poll(0.2):
            message = parent.recv()
            if message["type"] == "status":
                status = message["engines"]
                if all(v["state"] in ("ready", "error") for v in status.values()) and len(status) >= 5:
                    break
    print("engines:", {k: (v["engine"], v["state"], v["detail"]) for k, v in status.items()})
    script = parse(SCRIPT, packs.get("en"))
    log = TakeLog()
    ui = Listener_()
    session = Session(log, SessionSettings(), ui, script, packs.get("en"), packs.get("pt-BR"))
    session.start()
    parent.send({"type": "listen", "active": True})
    audio_conn.send(("reset", 0))
    silence = np.zeros(int(16000 * 1.2), dtype=np.int16)
    stream = np.concatenate([silence] + [np.concatenate([synth(u), silence]) for u in UTTERANCES] + [silence, silence])
    position = 0
    chunk = 480
    start = time.time()
    while position < len(stream):
        audio_conn.send((position, stream[position:position + chunk].tobytes()))
        position += chunk
        target = start + position / 16000 / 4
        while time.time() < target:
            while parent.poll(0):
                route(parent.recv(), session, parent)
            time.sleep(0.002)
    end_wait = time.time() + 120
    duration = len(stream) / 16000
    settle = None
    while time.time() < end_wait:
        while parent.poll(0.05):
            route(parent.recv(), session, parent)
        session.tick(position / 16000)
        if session.words_horizon >= duration - 0.3:
            settle = settle or time.time() + 8
            if time.time() > settle:
                break
    session.stop()
    print("takes:")
    for take in log.takes:
        print(f"  #{take.id} s{take.sentence} {take.status:9} {take.reason:8} {take.start:6.2f}-{(take.end or 0):6.2f} score={take.score} flagged={[f['text'] for f in take.flagged]}")
    print("markers:", [(m.kind, m.label, round(m.start, 2)) for m in log.markers])
    process.terminate()
    listener.close()
    statuses = [(t.sentence, t.status) for t in log.takes]
    ok = (0, "complete") in statuses and (1, "rejected") in statuses and (1, "complete") in statuses and (2, "complete") in statuses
    print("RESULT:", "OK" if ok else "UNEXPECTED")
    return 0 if ok else 1


def route(message: dict, session: Session, connection) -> None:
    kind = message.get("type")
    if kind in ("vad", "words", "command", "score", "progress"):
        session.on_engine(message)
        if kind == "command":
            print("  command:", message["action"], round(message["start"], 2))
        if kind == "words" and message.get("final"):
            print("  words:", " ".join(w["text"] for w in message["words"]), round(message["words"][0]["start"], 2))
    for _, args in list(session.listener.events):
        pass
    for name, args in session.listener.events:
        if name == "request":
            connection.send(args[0])
    session.listener.events = [e for e in session.listener.events if e[0] != "request"]


if __name__ == "__main__":
    sys.exit(main())
