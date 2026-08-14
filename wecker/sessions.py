"""Findet Claude-Code-Sessions ueber alle Config-Profile hinweg.

``claude agents --json`` listet nur Sessions des eigenen CLAUDE_CONFIG_DIR.
Wer alle Sessions sehen will, muss das Kommando je Profil aufrufen. Die
Profile werden anhand von ``~/.claude*/projects`` entdeckt, nicht
hartkodiert.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

AGENTS_TIMEOUT_SECONDS = 20

# Nur Sessions, die auf Eingaben warten, duerfen geweckt werden. Eine
# beschaeftigte Session wuerde die Nachricht mitten in ihren Turn bekommen.
WAKEABLE_STATUS = frozenset({"idle", "waiting"})


@dataclass(frozen=True)
class Session:
    profile: Path
    session_id: str
    pid: int
    name: str
    status: str | None
    cwd: str | None

    @property
    def is_wakeable(self) -> bool:
        return self.status in WAKEABLE_STATUS

    @property
    def log_path(self) -> Path | None:
        matches = sorted(self.profile.glob(f"projects/*/{self.session_id}.jsonl"))
        return matches[0] if matches else None


def discover_profiles(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    return sorted(p for p in home.glob(".claude*") if (p / "projects").is_dir())


def list_sessions(profile: Path, runner=subprocess.run) -> list[Session]:
    """Liest die interaktiven Sessions eines Profils."""
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(profile)}
    try:
        result = runner(
            ["claude", "agents", "--json"],
            env=env,
            capture_output=True,
            text=True,
            timeout=AGENTS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    if result.returncode != 0:
        return []

    try:
        entries = json.loads(result.stdout)
    except ValueError:
        return []
    if not isinstance(entries, list):
        return []

    sessions = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        pid, session_id = entry.get("pid"), entry.get("sessionId")
        if not isinstance(pid, int) or not isinstance(session_id, str):
            continue
        sessions.append(
            Session(
                profile=profile,
                session_id=session_id,
                pid=pid,
                name=str(entry.get("name") or session_id[:8]),
                status=entry.get("status"),
                cwd=entry.get("cwd"),
            )
        )
    return sessions


def list_all_sessions(home: Path | None = None, runner=subprocess.run) -> list[Session]:
    sessions = []
    for profile in discover_profiles(home):
        sessions.extend(list_sessions(profile, runner=runner))
    return sessions
