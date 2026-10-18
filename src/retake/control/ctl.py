from __future__ import annotations

import socket
import sys

from .. import paths

ACTIONS = {
    "next": "next",
    "back": "back",
    "again": "again",
    "retake": "again",
    "pause": "pause",
    "resume": "resume",
    "toggle-pause": "toggle_pause",
    "mark": "mark",
    "listen": "listen",
    "flag": "flag",
    "record": "record",
    "stop": "stop",
    "rehearse": "rehearse",
    "layout": "layout",
    "show": "show",
}


def send(action: str, argument: str = "") -> str:
    if action not in ACTIONS:
        raise SystemExit(f"unknown action: {action} (available: {', '.join(sorted(ACTIONS))})")
    path = paths.control_socket()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        try:
            client.connect(str(path))
        except (FileNotFoundError, ConnectionRefusedError):
            raise SystemExit("Retake is not running")
        client.sendall(f"{ACTIONS[action]} {argument}".strip().encode() + b"\n")
        try:
            return client.recv(1024).decode().strip()
        except TimeoutError:
            return "ok"


def main(arguments: list[str]) -> int:
    if not arguments:
        print("usage: retake ctl <" + "|".join(sorted(ACTIONS)) + "> [argument]")
        return 1
    reply = send(arguments[0], " ".join(arguments[1:]))
    if reply and reply != "ok":
        print(reply, file=sys.stderr)
        return 1
    return 0
