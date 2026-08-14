"""continuum: weckt rate-limitierte Claude-Code-Sessions.

Ein Tick prueft alle Sessions aller Config-Profile und stupst jede an, die
im Rate-Limit haengt und auf Eingaben wartet. Die Reset-Zeit wird bewusst
NICHT ausgewertet: Ein zu frueher Versuch kostet nur eine Zeile im Log,
waehrend das Parsen einer lokalisierten Uhrzeit still danebengreifen kann.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from continuum.detect import read_limit_state
from continuum.poke import poke, socket_path
from continuum.sessions import Session, list_all_sessions
from continuum.state import LogFingerprint, PokeMemory

DEFAULT_MESSAGE = "continue"
STATE_DIR = Path.home() / ".local" / "state" / "continuum"

log = logging.getLogger("continuum")


def run_tick(message: str, dry_run: bool, memory: PokeMemory, sessions=None) -> int:
    poked = 0
    for session in list_all_sessions() if sessions is None else sessions:
        if _handle(session, message, dry_run, memory):
            poked += 1
    if not dry_run:
        memory.save()
    return poked


def _handle(session: Session, message: str, dry_run: bool, memory: PokeMemory) -> bool:
    log_path = session.log_path
    if log_path is None:
        return False

    # Fingerprint VOR dem Lesen nehmen: waechst das Log waehrend der Analyse,
    # gilt der neue Inhalt als ungesehen und der naechste Tick schaut erneut hin.
    fingerprint = LogFingerprint.of(log_path)

    state = read_limit_state(log_path)
    if not state.is_limited:
        memory.forget(session.session_id)
        return False

    label = f"{session.name} (pid {session.pid}, {session.profile.name})"
    if not session.is_wakeable:
        log.info("%s: limited, but status=%s, not poked", label, session.status)
        return False

    if not memory.should_poke(session.session_id, fingerprint):
        log.debug("%s: unchanged since the last attempt", label)
        return False

    if dry_run:
        log.info("%s: would poke (reset %s)", label, state.reset_hint or "unknown")
        return True

    if not socket_path(session.pid).exists():
        log.warning("%s: no socket at %s", label, socket_path(session.pid))
        return False

    try:
        poke(session.pid, message, session_id=session.session_id)
    except OSError as error:
        log.warning("%s: delivery failed: %s", label, error)
        return False

    memory.record(session.session_id, fingerprint)
    log.info("%s: poked (reset %s)", label, state.reset_hint or "unknown")
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="continuum",
        description="Continues Claude Code sessions when their rate limit window opens again.",
    )
    parser.add_argument("--message", default=DEFAULT_MESSAGE, help="text to deliver")
    parser.add_argument("--dry-run", action="store_true", help="show only, send nothing")
    parser.add_argument("--status", action="store_true", help="print the state of all sessions")
    parser.add_argument("--verbose", action="store_true", help="debug output")
    parser.add_argument("--state-file", type=Path, default=STATE_DIR / "poked.json")
    return parser


def print_status() -> int:
    for session in list_all_sessions():
        try:
            log_path = session.log_path
            state = read_limit_state(log_path) if log_path else None
        except OSError as error:
            print(f"{'?':<10} {session.name:<20} pid={session.pid:<7} unreadable: {error}")
            continue
        limited = "LIMITED" if state and state.is_limited else "ok"
        reset = f" reset={state.reset_hint}" if state and state.reset_hint else ""
        socket_note = "" if socket_path(session.pid).exists() else "  [kein Socket]"
        print(
            f"{limited:<10} {session.name:<20} pid={session.pid:<7} "
            f"status={session.status or '-':<8} {session.profile.name}{reset}{socket_note}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    if args.status:
        return print_status()

    memory = PokeMemory(args.state_file)
    poked = run_tick(args.message, args.dry_run, memory)
    log.info("Tick done, %d session(s) poked", poked)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
