from __future__ import annotations

from datetime import datetime

from day_overview import overview
from temporal_parser import norm, parse
from time_store import DEFAULT_TZ, tz


def _relative_day(text: str) -> str | None:
    """Resolve only objective relative-day references.

    This is temporal data extraction, not intent routing. It deliberately does not
    decide what action the user wants and never mutates state.
    """
    normalized = f" {norm(text)} "
    if ' amanha ' in normalized:
        return 'tomorrow'
    if ' hoje ' in normalized:
        return 'today'
    return None


def safe_read_fallback(text: str) -> str | None:
    """Read-only resilience when the semantic brain is unavailable.

    A fallback answer is allowed only for a clearly interrogative message whose day
    can be resolved objectively. Mutations never pass through this path.
    """
    raw = str(text or '').strip()
    if not raw or '?' not in raw:
        return None

    relative = _relative_day(raw)
    if relative is not None:
        return overview(relative)

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
