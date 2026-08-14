"""Stellt einer laufenden Claude-Code-Session eine Nachricht zu.

Claude Code oeffnet je Prozess einen Unix-Domain-Socket unter
``$XDG_RUNTIME_DIR/cc-socks/<pid>.sock`` (sonst ``/tmp/cc-socks``) und liest
dort zeilenweise JSON. Eine Nutzernachricht sieht so aus::

    {"type":"user","priority":"now","message":{"content":"continue"}}

``session_id`` wird von der Gegenstelle gegen die eigene Session geprueft
und verworfen, wenn sie nicht passt. Das schuetzt davor, nach einem
PID-Recycling einen fremden Prozess anzusprechen.
"""

from __future__ import annotations

import json
import os
import socket
import stat
from pathlib import Path

CONNECT_TIMEOUT_SECONDS = 5


def socket_dir() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return Path(runtime if runtime else "/tmp") / "cc-socks"


def socket_path(pid: int) -> Path:
    return socket_dir() / f"{pid}.sock"


def build_message(text: str, session_id: str | None = None, priority: str = "now") -> dict:
    message = {"type": "user", "priority": priority, "message": {"content": text}}
    if session_id:
        message["session_id"] = session_id
    return message


def is_own_socket(path: Path) -> bool:
    """Gehoert der Socket dem eigenen Benutzer?

    ``/tmp/cc-socks`` liegt in einem weltweit beschreibbaren Verzeichnis. Auf
    einem Mehrbenutzersystem koennte dort ein fremder Prozess lauschen. Die
    Zustellung soll niemandem sonst etwas zuschicken.
    """
    try:
        info = path.stat()
    except OSError:
        return False
    return stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid()


def poke(pid: int, text: str, session_id: str | None = None) -> None:
    """Sendet die Nachricht. Wirft OSError, wenn der Socket nicht erreichbar ist."""
    target = socket_path(pid)
    if not is_own_socket(target):
        raise PermissionError(f"{target} is not owned by the current user")

    payload = json.dumps(build_message(text, session_id)).encode("utf-8") + b"\n"
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(CONNECT_TIMEOUT_SECONDS)
    try:
        connection.connect(str(target))
        connection.sendall(payload)
    finally:
        connection.close()
