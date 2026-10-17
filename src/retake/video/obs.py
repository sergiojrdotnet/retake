from __future__ import annotations

import base64
import hashlib
import json
import threading
import uuid


class ObsError(RuntimeError):
    pass


class ObsClient:
    def __init__(self, host: str = "localhost", port: int = 4455, password: str = ""):
        self.url = f"ws://{host}:{port}"
        self.password = password
        self.socket = None
        self.lock = threading.Lock()

    def connect(self, timeout: float = 3.0) -> None:
        try:
            from websockets.sync.client import connect
        except ImportError as error:
            raise ObsError("python-websockets is required for OBS") from error
        try:
            self.socket = connect(self.url, open_timeout=timeout, subprotocols=["obswebsocket.json"])
        except OSError as error:
            raise ObsError(f"OBS is not reachable at {self.url}: {error}") from error
        hello = json.loads(self.socket.recv(timeout=timeout))
        identify = {"rpcVersion": 1, "eventSubscriptions": 0}
        auth = hello.get("d", {}).get("authentication")
        if auth:
            secret = base64.b64encode(hashlib.sha256((self.password + auth["salt"]).encode()).digest()).decode()
            identify["authentication"] = base64.b64encode(hashlib.sha256((secret + auth["challenge"]).encode()).digest()).decode()
        self.socket.send(json.dumps({"op": 1, "d": identify}))
        reply = json.loads(self.socket.recv(timeout=timeout))
        if reply.get("op") != 2:
            raise ObsError("OBS rejected the connection (check the password)")

    def close(self) -> None:
        if self.socket is not None:
            self.socket.close()
            self.socket = None

    def call(self, request_type: str, data: dict | None = None, timeout: float = 5.0) -> dict:
        if self.socket is None:
            self.connect()
        request_id = uuid.uuid4().hex
        with self.lock:
            self.socket.send(json.dumps({"op": 6, "d": {"requestType": request_type, "requestId": request_id, "requestData": data or {}}}))
            while True:
                message = json.loads(self.socket.recv(timeout=timeout))
                if message.get("op") == 7 and message["d"].get("requestId") == request_id:
                    status = message["d"].get("requestStatus", {})
                    if not status.get("result"):
                        raise ObsError(f"{request_type}: {status.get('comment') or status.get('code')}")
                    return message["d"].get("responseData") or {}

    def scenes(self) -> list[str]:
        return [s["sceneName"] for s in reversed(self.call("GetSceneList").get("scenes", []))]

    def set_scene(self, name: str) -> None:
        self.call("SetCurrentProgramScene", {"sceneName": name})

    def start_record(self) -> None:
        self.call("StartRecord")

    def stop_record(self) -> str | None:
        return self.call("StopRecord", timeout=30).get("outputPath")

    def chapter(self, name: str) -> None:
        try:
            self.call("CreateRecordChapter", {"chapterName": name})
        except ObsError:
            pass

    def pause(self, paused: bool) -> None:
        self.call("PauseRecord" if paused else "ResumeRecord")
