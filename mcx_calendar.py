"""
mcx_calendar.py — MCX trading calendar (holiday + session aware, IST).

MCX commodity day = morning session 09:00–17:00 IST + evening session
17:00–23:30 IST (continuous on a normal day). On many holidays the morning
session is closed but the evening session trades; some holidays close both.
This module encodes that so the autonomous monitor never acts on a closed
session (which would mean stale data / spurious alerts).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

IST_OFFSET = timedelta(hours=5, minutes=30)

# Session boundaries — minutes since IST midnight
_MORNING_START = 9 * 60          # 09:00
_EVENING_START = 17 * 60         # 17:00  (morning ends / evening begins)
_EVENING_END   = 23 * 60 + 30    # 23:30

# date "YYYY-MM-DD" -> (morning_open, evening_open).
# A weekday NOT in this map = normal day (both sessions open).
# Source: MCX 2026 holiday circular.
_HOLIDAYS = {
    "2026-01-01": (True,  False),  # New Year Day        — morning only
    "2026-01-26": (False, False),  # Republic Day        — closed
    "2026-03-03": (False, True),   # Holi                — evening only
    "2026-03-26": (False, True),   # Shri Ram Navmi
    "2026-03-31": (False, True),   # Shri Mahavir Jayanti
    "2026-04-03": (False, False),  # Good Friday         — closed
    "2026-04-14": (False, True),   # Ambedkar Jayanti
    "2026-05-01": (False, True),   # Maharashtra Day
    "2026-05-28": (False, True),   # Bakri Id
    "2026-06-26": (False, True),   # Moharram
    "2026-09-14": (False, True),   # Ganesh Chaturthi
    "2026-10-02": (False, False),  # Gandhi Jayanti      — closed
    "2026-10-20": (False, True),   # Dassera
    "2026-11-10": (False, True),   # Diwali-Balipratipada
    "2026-11-24": (False, True),   # Guru Nanak Jayanti
    "2026-12-25": (False, False),  # Christmas           — closed
}


def ist_now() -> datetime:
    return datetime.now(timezone.utc) + IST_OFFSET


def _sessions(ist: datetime) -> tuple[bool, bool]:
    """(morning_open, evening_open) for the given IST date."""
    return _HOLIDAYS.get(ist.strftime("%Y-%m-%d"), (True, True))


def is_market_open(ist: datetime | None = None) -> bool:
    """True if MCX is in a tradeable session right now (weekend + holiday aware)."""
    ist = ist or ist_now()
    if ist.weekday() >= 5:                       # Sat/Sun
        return False
    morning_open, evening_open = _sessions(ist)
    mins = ist.hour * 60 + ist.minute
    if _MORNING_START <= mins < _EVENING_START and morning_open:
        return True
    if _EVENING_START <= mins <= _EVENING_END and evening_open:
        return True
    return False


def session_label(ist: datetime | None = None) -> str:
    """Short human-readable status (for logs)."""
    ist = ist or ist_now()
    if ist.weekday() >= 5:
        return "weekend"
    morning_open, evening_open = _sessions(ist)
    if not morning_open and not evening_open:
        return "MCX holiday — full close"
    if (morning_open, evening_open) != (True, True):
        return "MCX partial holiday (one session closed)"
    return "normal session"
