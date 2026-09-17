from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from temporal_parser import MONTHS, WEEKDAYS, norm
from time_store import DEFAULT_TZ, tz


@dataclass(frozen=True)
class TemporalRange:
    start: date
    end: date
    label: str


def _today() -> date:
    return datetime.now(tz(DEFAULT_TZ)).date()


def _month_shift(year: int, month: int, offset: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + offset
    return index // 12, (index % 12) + 1


def _month_end(year: int, month: int) -> date:
    ny, nm = _month_shift(year, month, 1)
    return date(ny, nm, 1) - timedelta(days=1)


def _valid_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _explicit_numeric(text: str, today: date) -> date | None:
    m = re.search(r'\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b', text)
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    year = int(m.group(3) or today.year)
    if year < 100:
        year += 2000
    candidate = _valid_date(year, month, day)
    if candidate is None:
        return None
    if m.group(3) is None and candidate < today:
        candidate = _valid_date(year + 1, month, day)
    return candidate


def _named_month_date(text: str, today: date) -> date | None:
    for name, month in MONTHS.items():
        month_name = norm(name)
        m = re.search(rf'\b(?:dia\s+)?(\d{{1,2}})\s+(?:de\s+)?{re.escape(month_name)}(?:\s+de\s+(\d{{4}}))?\b', text)
        if not m:
            continue
        day = int(m.group(1))
        year = int(m.group(2) or today.year)
        candidate = _valid_date(year, month, day)
        if candidate is None:
            return None
        if m.group(2) is None and candidate < today:
            candidate = _valid_date(year + 1, month, day)
        return candidate
    return None


def _day_of_month(text: str, today: date) -> date | None:
    m = re.search(r'\bdia\s+(\d{1,2})\b', text)
    if not m:
        return None
    day = int(m.group(1))
    candidate = _valid_date(today.year, today.month, day)
    if candidate is not None and candidate >= today:
        return candidate
    year, month = _month_shift(today.year, today.month, 1)
    return _valid_date(year, month, day)


def _weekday_date(text: str, today: date) -> date | None:
    found: tuple[str, int] | None = None
    for name, weekday in sorted(WEEKDAYS.items(), key=lambda pair: len(pair[0]), reverse=True):
        n = norm(name)
        if re.search(rf'\b{re.escape(n)}\b', text):
            found = (n, weekday)
            break
    if found is None:
        return None

    _, weekday = found
    if re.search(r'\bsemana\s+que\s+vem\b', text):
        next_monday = today + timedelta(days=(7 - today.weekday()))
        return next_monday + timedelta(days=weekday)

    days = (weekday - today.weekday()) % 7
    if days == 0 and re.search(r'\bproxim[ao]\b', text):
        days = 7
    return today + timedelta(days=days)


def resolve_temporal_range(raw: str, *, today: date | None = None) -> TemporalRange | None:
    """Extrai referência temporal objetiva sem decidir intenção nem executar ações."""
    current = today or _today()
    text = norm(raw)
    if not text:
        return None

    if re.search(r'\bdepois\s+de\s+amanha\b', text):
        target = current + timedelta(days=2)
        return TemporalRange(target, target, 'depois de amanhã')
    if re.search(r'\bamanha\b', text):
        target = current + timedelta(days=1)
        return TemporalRange(target, target, 'amanhã')
    if re.search(r'\bhoje\b', text):
        return TemporalRange(current, current, 'hoje')

    m = re.search(r'\bdaqui\s+a\s+(\d+)\s+dias?\b', text)
    if m:
        target = current + timedelta(days=int(m.group(1)))
        return TemporalRange(target, target, target.strftime('%d/%m/%Y'))

    target = _explicit_numeric(text, current) or _named_month_date(text, current) or _day_of_month(text, current) or _weekday_date(text, current)
    if target is not None:
        return TemporalRange(target, target, target.strftime('%d/%m/%Y'))

    if re.search(r'\b(?:semana\s+que\s+vem|proxima\s+semana)\b', text):
        next_monday = current + timedelta(days=(7 - current.weekday()))
        return TemporalRange(next_monday, next_monday + timedelta(days=6), 'semana que vem')
    if re.search(r'\b(?:esta\s+semana|essa\s+semana|nesta\s+semana)\b', text):
        end = current + timedelta(days=(6 - current.weekday()))
        return TemporalRange(current, end, 'esta semana')

    if re.search(r'\b(?:mes\s+que\s+vem|proximo\s+mes)\b', text):
        year, month = _month_shift(current.year, current.month, 1)
        start = date(year, month, 1)
        return TemporalRange(start, _month_end(year, month), 'mês que vem')
    if re.search(r'\b(?:este\s+mes|esse\s+mes|neste\s+mes)\b', text):
        return TemporalRange(current, _month_end(current.year, current.month), 'este mês')

    return None
