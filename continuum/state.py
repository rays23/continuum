"""Merkt sich, in welchem Log-Zustand zuletzt geweckt wurde.

Ohne dieses Gedaechtnis wuerde jeder Tick dieselbe wartende Session erneut
anstupsen. Gemerkt wird Groesse und mtime des Session-Logs zum Zeitpunkt des
Weckversuchs: Erst wenn sich das Log seither veraendert hat, ist ein neuer
Versuch faellig. Ein Weckversuch selbst erzeugt einen neuen Log-Eintrag,
also loest jeder Versuch genau einen Nachfolger aus statt einer Flut.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LogFingerprint:
    size: int
    mtime_ns: int

    @classmethod
    def of(cls, path: Path) -> "LogFingerprint | None":
        try:
            info = path.stat()
        except OSError:
            return None
        return cls(size=info.st_size, mtime_ns=info.st_mtime_ns)

    def as_dict(self) -> dict:
        return {"size": self.size, "mtime_ns": self.mtime_ns}

    @classmethod
    def from_dict(cls, raw: object) -> "LogFingerprint | None":
        if not isinstance(raw, dict):
            return None
        size, mtime_ns = raw.get("size"), raw.get("mtime_ns")
        if not isinstance(size, int) or not isinstance(mtime_ns, int):
            return None
        return cls(size=size, mtime_ns=mtime_ns)


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

    def should_poke(self, session_id: str, fingerprint: LogFingerprint | None) -> bool:
        if fingerprint is None:
            return False
        return LogFingerprint.from_dict(self._entries.get(session_id)) != fingerprint

    def record(self, session_id: str, fingerprint: LogFingerprint | None) -> None:
        if fingerprint is None:
            return
        self._entries[session_id] = fingerprint.as_dict()

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
