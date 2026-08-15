"""Merkt sich je Session, wann der naechste Anstoss faellig ist.

Frueher merkte sich continuum den Log-Zustand und stiess bei jeder Aenderung
erneut an. Im Dauerbetrieb ergab das waehrend eines vierstuendigen Limits rund
zwanzig Anstoesse, die sich in der Warteschlange der blockierten Session
stapelten. Jetzt zaehlt allein der Zeitplan.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Plan:
    attempts: int = 0
    next_attempt: datetime | None = None

    def is_due(self, now: datetime) -> bool:
        return self.next_attempt is None or now >= self.next_attempt


class PokeMemory:
    def __init__(self, path: Path):
        self.path = path
        self._entries = self._load()

    def _load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def plan_for(self, session_id: str) -> Plan:
        entry = self._entries.get(session_id)
        if not isinstance(entry, dict):
            return Plan()

        attempts = entry.get("attempts")
        timestamp = entry.get("next_attempt_ts")
        return Plan(
            attempts=attempts if isinstance(attempts, int) and attempts >= 0 else 0,
            next_attempt=_to_datetime(timestamp),
        )

    def schedule(self, session_id: str, attempts: int, next_attempt: datetime) -> None:
        self._entries[session_id] = {
            "attempts": attempts,
            "next_attempt_ts": next_attempt.timestamp(),
            "next_attempt_iso": next_attempt.isoformat(timespec="seconds"),
        }

    def forget(self, session_id: str) -> None:
        self._entries.pop(session_id, None)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Prozesseigener Temp-Name: zwei gleichzeitige Laeufe (LaunchAgent plus
        # Aufruf von Hand) duerfen sich nicht dieselbe Datei zerschreiben.
        temporary = self.path.with_suffix(f".{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps(self._entries, indent=2), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise


def _to_datetime(timestamp: object) -> datetime | None:
    if not isinstance(timestamp, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
