"""continuum: setzt rate-limitierte Claude-Code-Sessions fort.

Ein Tick prueft alle Sessions aller Config-Profile und stupst jede an, die
im Rate-Limit haengt und auf Eingaben wartet.

Ausloeser bleibt das Pollen. Die Reset-Zeit wirkt nur als Bremse, damit sich
waehrend eines langen Limits keine Nachrichten in der Warteschlange der
blockierten Session stapeln. Ist sie nicht lesbar, waechst der Abstand
zwischen den Versuchen stattdessen an.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from continuum.detect import read_limit_state
from continuum.poke import poke, socket_path
from continuum.schedule import GRACE, MAX_WAIT, backoff_delay, parse_reset_time
from continuum.sessions import Session, list_all_sessions
from continuum.state import PokeMemory

DEFAULT_MESSAGE = "continue"
STATE_DIR = Path.home() / ".local" / "state" / "continuum"

log = logging.getLogger("continuum")


def run_tick(
    message: str,
    dry_run: bool,
    memory: PokeMemory,
    sessions=None,
    now: datetime | None = None,
) -> int:
    moment = now or datetime.now().astimezone()
    poked = 0
    for session in list_all_sessions() if sessions is None else sessions:
        if _handle(session, message, dry_run, memory, moment):
            poked += 1
    if not dry_run:
        memory.save()
    return poked


def _handle(
    session: Session, message: str, dry_run: bool, memory: PokeMemory, now: datetime
) -> bool:
    log_path = session.log_path
    if log_path is None:
        return False

    state = read_limit_state(log_path)
    if not state.is_limited:
        memory.forget(session.session_id)
        return False

    label = f"{session.name} (pid {session.pid}, {session.profile.name})"
    if not session.is_wakeable:
        log.info("%s: limited, but status=%s, not poked", label, session.status)
        return False

    plan = memory.plan_for(session.session_id)
    if not plan.is_due(now):
        log.debug("%s: next attempt at %s", label, plan.next_attempt)
        return False

    # Die Reset-Zeit bremst nur. Faellt sie aus, uebernimmt der Backoff.
    # Anker ist der Zeitpunkt des Limit-Eintrags: "7pm" meint das naechste 19 Uhr
    # NACH der Meldung, nicht nach jetzt. Sonst schoebe eine laengst abgelaufene
    # Reset-Zeit sich selbst auf den naechsten Tag.
    reset_at = parse_reset_time(state.reset_hint, state.logged_at or now)
    if reset_at is not None and now < reset_at:
        wait_until = min(reset_at + GRACE, now + MAX_WAIT)
        if not dry_run:
            memory.schedule(session.session_id, plan.attempts, wait_until)
        log.info("%s: waiting for the reset at %s", label, state.reset_hint)
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

    attempts = plan.attempts + 1
    memory.schedule(session.session_id, attempts, now + backoff_delay(attempts))
    log.info("%s: poked (attempt %d, reset %s)", label, attempts, state.reset_hint or "unknown")
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
