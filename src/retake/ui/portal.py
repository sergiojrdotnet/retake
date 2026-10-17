from __future__ import annotations

import secrets
import threading
from typing import Callable
from urllib.parse import unquote, urlparse

PORTAL = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
CHOOSER = "org.freedesktop.portal.FileChooser"


def available() -> bool:
    try:
        import jeepney  # noqa: F401
        from jeepney.io.blocking import open_dbus_connection

        connection = open_dbus_connection(bus="SESSION")
        connection.close()
        return True
    except Exception:
        return False


def _choose(method: str, title: str, options: dict, done: Callable[[list[str]], None]) -> None:
    from jeepney import DBusAddress, new_method_call
    from jeepney.bus_messages import MatchRule, message_bus
    from jeepney.io.blocking import open_dbus_connection

    connection = open_dbus_connection(bus="SESSION")
    try:
        token = "retake" + secrets.token_hex(4)
        sender = connection.unique_name.lstrip(":").replace(".", "_")
        handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        rule = MatchRule(type="signal", interface="org.freedesktop.portal.Request", member="Response", path=handle)
        connection.send_and_get_reply(message_bus.AddMatch(rule))
        portal = DBusAddress(PATH, bus_name=PORTAL, interface=CHOOSER)
        payload = {"handle_token": ("s", token), **options}
        with connection.filter(rule) as queue:
            connection.send_and_get_reply(new_method_call(portal, method, "ssa{sv}", ("", title, payload)))
            reply = connection.recv_until_filtered(queue, timeout=600)
        code, results = reply.body
        if code != 0:
            done([])
            return
        uris = results.get("uris", ("as", []))[1]
        done([unquote(urlparse(uri).path) for uri in uris])
    finally:
        connection.close()


def open_file(title: str, patterns: list[tuple[str, list[str]]], done: Callable[[list[str]], None], multiple: bool = False) -> None:
    filters = ("a(sa(us))", [(name, [(0, glob) for glob in globs]) for name, globs in patterns])
    options = {"filters": filters}
    if multiple:
        options["multiple"] = ("b", True)
    threading.Thread(target=_safe, args=("OpenFile", title, options, done), daemon=True).start()


def open_directory(title: str, done: Callable[[list[str]], None], start: str = "") -> None:
    options = {"directory": ("b", True)}
    if start:
        options["current_folder"] = ("ay", start.encode() + b"\0")
    threading.Thread(target=_safe, args=("OpenFile", title, options, done), daemon=True).start()


def _safe(method: str, title: str, options: dict, done: Callable[[list[str]], None]) -> None:
    try:
        _choose(method, title, options, done)
    except Exception:
        done(None)
