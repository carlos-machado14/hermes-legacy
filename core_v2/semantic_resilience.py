from __future__ import annotations

from datetime import datetime

from day_overview import overview
from temporal_parser import parse
from time_store import DEFAULT_TZ, tz


def safe_read_fallback(text: str) -> str | None:
    """Fallback read-only when the semantic brain is unavailable.

    This intentionally does not classify actions or entities from keywords. It only
    answers a narrow class of safe questions when two objective signals exist:
    1) the user clearly sent a question; and
    2) the temporal parser resolved a concrete day.

    It never mutates state. Any action still requires the semantic brain.
    """
    raw = str(text or '').strip()
    if not raw or '?' not in raw:
        return None

    parsed = parse(raw)
    if not parsed or not parsed.get('next_run_at'):
        return None

    zone = tz(parsed.get('timezone') or DEFAULT_TZ)
    target = datetime.fromtimestamp(int(parsed['next_run_at']), zone).date()
    today = datetime.now(zone).date()
    delta = (target - today).days

    if delta == 0:
        return overview('today')
    if delta == 1:
        return overview('tomorrow')
    return None
