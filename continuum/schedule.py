"""Bestimmt, wann der naechste Anstoss faellig ist.

Der Ausloeser bleibt das Pollen. Die Reset-Zeit dient nur als Bremse: Ist sie
lesbar und liegt in der Zukunft, wird bis dahin nicht angestossen. Greift das
Parsen daneben, faellt alles auf einen wachsenden Abstand zurueck, und der
Fehler kostet hoechstens ein paar zusaetzliche Versuche.

Grund fuer die Bremse: Eine blockierte Session legt eingehende Nachrichten in
ihre Warteschlange, ohne sie abzuarbeiten. Ohne Bremse stapeln sich waehrend
eines langen Limits zwanzig `continue`, die nach dem Reset alle auf einmal
zugestellt werden.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# "7pm", "6:50pm", "12am (Europe/Berlin)", "19:00"
TIME_PATTERN = re.compile(
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<meridiem>am|pm)?\b",
    re.IGNORECASE,
)
ZONE_PATTERN = re.compile(r"\(([A-Za-z]+/[A-Za-z_\-+0-9]+)\)")

BACKOFF_STEPS = [
    timedelta(minutes=10),
    timedelta(minutes=20),
    timedelta(minutes=40),
    timedelta(minutes=80),
    timedelta(minutes=120),
]

# Kleiner Puffer nach dem Reset, damit der Anstoss nicht auf die Sekunde faellt.
GRACE = timedelta(minutes=1)

# Obergrenze fuer die Bremse. Greift das Parsen der Reset-Zeit daneben, wartet
# continuum hoechstens so lange, danach uebernimmt wieder der Backoff-Poll.
MAX_WAIT = timedelta(hours=2)


def parse_reset_time(hint: str | None, now: datetime) -> datetime | None:
    """Wandelt "7pm (Europe/Berlin)" in einen Zeitpunkt in der Zukunft."""
    if not hint:
        return None

    match = TIME_PATTERN.search(hint)
    if match is None:
        return None

    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    meridiem = (match.group("meridiem") or "").lower()

    if meridiem:
        if not 1 <= hour <= 12 or minute > 59:
            return None
        hour = hour % 12
        if meridiem == "pm":
            hour += 12
    elif hour > 23 or minute > 59:
        return None

    zone = _zone_from(hint) or now.tzinfo
    local_now = now.astimezone(zone)
    reset = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if reset <= local_now:
        reset += timedelta(days=1)
    return reset


def backoff_delay(attempts: int) -> timedelta:
    """Abstand nach ``attempts`` erfolglosen Versuchen."""
    index = max(0, attempts - 1)
    return BACKOFF_STEPS[min(index, len(BACKOFF_STEPS) - 1)]


def _zone_from(hint: str) -> ZoneInfo | None:
    match = ZONE_PATTERN.search(hint)
    if match is None:
        return None
    try:
        return ZoneInfo(match.group(1))
    except (ZoneInfoNotFoundError, ValueError):
        return None
