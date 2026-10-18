from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

# "RTK1" in the SQLite header, so the file is recognizable as a Retake project (see retake.xml).
APPLICATION_ID = 0x52544B31
SCHEMA = """
CREATE TABLE project (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE items (id TEXT PRIMARY KEY, position INTEGER NOT NULL, data TEXT NOT NULL);
CREATE TABLE logs (item TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE edits (item TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE snapshots (item TEXT PRIMARY KEY, text TEXT NOT NULL);
CREATE TABLE recordings (item TEXT NOT NULL, part INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY (item, part));
"""
ITEM_TABLES = ("logs", "edits", "snapshots", "recordings")


def _encode(data) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


class Store:
    """The .retake file: one SQLite database with the project, its items, and each item's takes,
    edit and script snapshot, plus the take log of a recording in progress. Every write lands
    whole or not at all, so a crash mid-recording loses nothing already written."""

    def __init__(self, path: Path, create: bool = False):
        self.path = path
        self._lock = threading.RLock()
        self._depth = 0
        if create and path.exists():
            raise FileExistsError(path)
        if not create and not path.is_file():
            raise FileNotFoundError(path)
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)
        try:
            if create:
                self.db.execute(f"PRAGMA application_id = {APPLICATION_ID}")
                self.db.executescript(SCHEMA)
            elif self.db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                raise ValueError(f"{path.name} is not a Retake project")
        except sqlite3.DatabaseError as error:
            self.db.close()
            raise ValueError(f"{path.name} is not a Retake project") from error
        except ValueError:
            self.db.close()
            raise

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def batch(self):
        """Several writes as one: all of them land, or none."""
        with self._lock:
            if self._depth == 0:
                self.db.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield
            except BaseException:
                self._depth -= 1
                if self._depth == 0:
                    self.db.execute("ROLLBACK")
                raise
            self._depth -= 1
            if self._depth == 0:
                self.db.execute("COMMIT")

    def _one(self, sql: str, *args):
        with self._lock:
            row = self.db.execute(sql, args).fetchone()
        return row[0] if row else None

    def _write(self, sql: str, *args) -> None:
        with self.batch():
            self.db.execute(sql, args)

    def project(self) -> dict:
        with self._lock:
            return {key: json.loads(value) for key, value in self.db.execute("SELECT key, value FROM project")}

    def items(self) -> list[dict]:
        with self._lock:
            return [json.loads(data) for (data,) in self.db.execute("SELECT data FROM items ORDER BY position")]

    def save_project(self, meta: dict, items: list[dict]) -> None:
        with self.batch():
            self.db.execute("DELETE FROM project")
            self.db.executemany("INSERT INTO project VALUES (?, ?)", [(key, _encode(value)) for key, value in meta.items()])
            self.db.execute("DELETE FROM items")
            self.db.executemany("INSERT INTO items VALUES (?, ?, ?)", [(item["id"], position, _encode(item)) for position, item in enumerate(items)])

    def log(self, item: str) -> dict | None:
        data = self._one("SELECT data FROM logs WHERE item = ?", item)
        return json.loads(data) if data else None

    def save_log(self, item: str, data: dict) -> None:
        self._write("INSERT OR REPLACE INTO logs VALUES (?, ?)", item, _encode(data))

    def edit(self, item: str) -> dict | None:
        data = self._one("SELECT data FROM edits WHERE item = ?", item)
        return json.loads(data) if data else None

    def save_edit(self, item: str, data: dict) -> None:
        self._write("INSERT OR REPLACE INTO edits VALUES (?, ?)", item, _encode(data))

    def snapshot(self, item: str) -> str | None:
        return self._one("SELECT text FROM snapshots WHERE item = ?", item)

    def save_snapshot(self, item: str, text: str) -> None:
        self._write("INSERT OR REPLACE INTO snapshots VALUES (?, ?)", item, text)

    def recording(self, item: str, part: int) -> dict | None:
        data = self._one("SELECT data FROM recordings WHERE item = ? AND part = ?", item, part)
        return json.loads(data) if data else None

    def save_recording(self, item: str, part: int, data: dict) -> None:
        self._write("INSERT OR REPLACE INTO recordings VALUES (?, ?, ?)", item, part, _encode(data))

    def drop_recording(self, item: str, part: int) -> None:
        self._write("DELETE FROM recordings WHERE item = ? AND part = ?", item, part)

    def forget(self, item: str) -> None:
        """Drops everything recorded for an item: takes, edit, snapshot, unfinished recordings."""
        with self.batch():
            for table in ITEM_TABLES:
                self.db.execute(f"DELETE FROM {table} WHERE item = ?", (item,))
