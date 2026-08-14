"""Erkennt am Session-Log, ob eine Claude-Code-Session im Rate-Limit haengt.

Claude Code schreibt den Limit-Fehler als assistant-Eintrag mit
``isApiErrorMessage: true`` ins Session-JSONL, zum Beispiel::

    You've hit your session limit · resets 7pm (Europe/Berlin)

Danach folgen noch system-/queue-operation-Zeilen. Massgeblich ist deshalb
immer der *letzte assistant-Eintrag*: Ist er ein Limit-Fehler, haengt die
Session. Kommt ein spaeterer assistant-Eintrag ohne Fehler, hat sie sich
erholt.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# Nur die letzten Bytes lesen; Session-Logs werden schnell mehrere MB gross.
TAIL_BYTES = 256 * 1024

# Trifft "session limit", "usage limit" und "limit reached" in einer
# API-Fehlermeldung. Bewusst eng gehalten, damit ein Verbindungsabbruch
# nicht als Rate-Limit durchgeht.
LIMIT_PATTERN = re.compile(r"\b(session|usage|rate)[ -]?limit\b|\blimit reached\b", re.IGNORECASE)

RESET_PATTERN = re.compile(r"\bresets?\s+(?P<hint>.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class LimitState:
    is_limited: bool
    reset_hint: str | None = None
    text: str | None = None


NOT_LIMITED = LimitState(is_limited=False)


def read_limit_state(path: Path) -> LimitState:
    """Liest den Limit-Zustand aus einem Session-JSONL."""
    entry = _last_assistant_entry(path)
    if entry is None:
        return NOT_LIMITED
    if not entry.get("isApiErrorMessage"):
        return NOT_LIMITED

    text = _entry_text(entry)
    if not LIMIT_PATTERN.search(text):
        return NOT_LIMITED

    return LimitState(is_limited=True, reset_hint=_reset_hint(text), text=text)


def _last_assistant_entry(path: Path) -> dict | None:
    for line in reversed(_tail_lines(path)):
        entry = _parse(line)
        if entry is not None and entry.get("type") == "assistant":
            return entry
    return None


def _tail_lines(path: Path) -> list[str]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            start = max(0, handle.tell() - TAIL_BYTES)
            handle.seek(start)
            raw = handle.read()
    except OSError:
        return []

    if start:
        # Angeschnittene erste Zeile verwerfen.
        _, _, raw = raw.partition(b"\n")
    return raw.decode("utf-8", errors="replace").splitlines()


def _parse(line: str) -> dict | None:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        parsed = json.loads(line)
    except (ValueError, RecursionError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _entry_text(entry: dict) -> str:
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [block.get("text", "") for block in content if isinstance(block, dict)]
        return " ".join(part for part in parts if part)
    return ""


def _reset_hint(text: str) -> str | None:
    match = RESET_PATTERN.search(text)
    return match.group("hint").strip() if match else None
