from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from time_store import DEFAULT_TZ, compute_next, tz

WEEKDAYS = {
    'segunda': 0, 'segunda-feira': 0,
    'terca': 1, 'terça': 1, 'terca-feira': 1, 'terça-feira': 1,
    'quarta': 2, 'quarta-feira': 2,
    'quinta': 3, 'quinta-feira': 3,
    'sexta': 4, 'sexta-feira': 4,
    'sabado': 5, 'sábado': 5,
    'domingo': 6,
}
MONTHS = {
    'janeiro': 1, 'fevereiro': 2, 'marco': 3, 'março': 3, 'abril': 4, 'maio': 5, 'junho': 6,
    'julho': 7, 'agosto': 8, 'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12,
}


def norm(text: str) -> str:
    raw = unicodedata.normalize('NFKD', str(text or ''))
    raw = ''.join(ch for ch in raw if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', raw.casefold()).strip()


def _time_matches(text: str) -> list[tuple[int, int, int, int]]:
    t = norm(text)
    out: list[tuple[int, int, int, int]] = []
    pattern = re.compile(
        r'\b(?:(?:as|a|at|por volta das)\s*(\d{1,2})(?::(\d{2}))?\s*(?:h|horas?)?'
        r'|(\d{1,2})(?::(\d{2}))?\s*(?:h|horas?))\b'
    )
    for m in pattern.finditer(t):
        hour = int(m.group(1) or m.group(3) or 0)
        minute = int(m.group(2) or m.group(4) or 0)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            out.append((hour, minute, m.start(), m.end()))
    return out


def _clock(text: str, default: str = '09:00') -> str:
    matches = _time_matches(text)
    if not matches:
        return default
    h, m, _, _ = matches[-1]
    return f'{h:02d}:{m:02d}'


def _window(text: str) -> tuple[str | None, str | None]:
    t = norm(text)
    m = re.search(
        r'\b(?:das|de)\s*(\d{1,2})(?::(\d{2}))?\s*(?:h|horas?)?\s*'
        r'(?:ate|a)\s*(\d{1,2})(?::(\d{2}))?\s*(?:h|horas?)?\b',
        t,
    )
    if not m:
        return None, None
    sh, sm = int(m.group(1)), int(m.group(2) or 0)
    eh, em = int(m.group(3)), int(m.group(4) or 0)
    if not (0 <= sh <= 23 and 0 <= eh <= 23 and 0 <= sm <= 59 and 0 <= em <= 59):
        return None, None
    return f'{sh:02d}:{sm:02d}', f'{eh:02d}:{em:02d}'


def _weekdays(text: str) -> list[int] | None:
    t = norm(text)
    if any(x in t for x in ('segunda a sexta', 'segunda-feira a sexta-feira', 'dias uteis')):
        return [0, 1, 2, 3, 4]
    if any(x in t for x in ('fim de semana', 'finais de semana', 'sabado e domingo')):
        return [5, 6]
    found: list[int] = []
    for name, value in WEEKDAYS.items():
        n = norm(name)
        if re.search(rf'\b(?:toda|todo|cada|na|no)?\s*{re.escape(n)}s?\b', t):
            if value not in found:
                found.append(value)
    return sorted(found) or None


def _relative_once(text: str, zone: ZoneInfo, now: datetime) -> datetime | None:
    t = norm(text)
    m = re.search(r'\b(?:daqui a|em)\s+(\d+)\s*(minuto|minutos|hora|horas|dia|dias)\b', t)
    if m and 'a cada' not in t:
        value, unit = int(m.group(1)), m.group(2)
        if 'minuto' in unit:
            return now + timedelta(minutes=value)
        if 'hora' in unit:
            return now + timedelta(hours=value)
        return now + timedelta(days=value)

    if 'amanha' in t:
        d = (now + timedelta(days=1)).date()
        hh, mm = map(int, _clock(text).split(':'))
        return datetime(d.year, d.month, d.day, hh, mm, tzinfo=zone)
    if 'hoje' in t:
        d = now.date()
        hh, mm = map(int, _clock(text).split(':'))
        candidate = datetime(d.year, d.month, d.day, hh, mm, tzinfo=zone)
        return candidate if candidate > now else None

    m = re.search(r'\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b', t)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3) or now.year)
        if year < 100:
            year += 2000
        hh, mm = map(int, _clock(text).split(':'))
        try:
            candidate = datetime(year, month, day, hh, mm, tzinfo=zone)
            if candidate <= now and not m.group(3):
                candidate = candidate.replace(year=year + 1)
            return candidate
        except ValueError:
            return None

    for name, wd in WEEKDAYS.items():
        n = norm(name)
        if re.search(rf'\b(?:na|no|nesta|neste|proxima|proximo)?\s*{re.escape(n)}\b', t):
            days = (wd - now.weekday()) % 7
            if days == 0:
                days = 7
            d = (now + timedelta(days=days)).date()
            hh, mm = map(int, _clock(text).split(':'))
            return datetime(d.year, d.month, d.day, hh, mm, tzinfo=zone)
    return None


def _yearly(text: str) -> dict[str, Any] | None:
    t = norm(text)
    if not any(x in t for x in ('todo ano', 'todos os anos', 'anualmente', 'anual')):
        return None
    day_match = re.search(r'\bdia\s+(\d{1,2})\b', t)
    month_num = next((number for name, number in MONTHS.items() if norm(name) in t), None)
    if not day_match or not month_num:
        return {'needs_clarification': 'Qual mês desse lembrete anual?'}
    return {'freq': 'yearly', 'month': month_num, 'day': int(day_match.group(1)), 'time': _clock(text)}


def _monthly(text: str) -> dict[str, Any] | None:
    t = norm(text)
    m = re.search(r'\b(?:todo|cada)\s+dia\s+(\d{1,2})\b', t)
    if not m:
        m = re.search(r'\bdia\s+(\d{1,2})\s+de\s+cada\s+mes\b', t)
    if m:
        return {'freq': 'monthly', 'day': max(1, min(31, int(m.group(1)))), 'time': _clock(text)}
    return None


def parse(text: str, *, timezone: str | None = None, now: datetime | None = None) -> dict[str, Any] | None:
    raw = str(text or '').strip()
    if not raw:
        return None
    zone_name = (timezone or DEFAULT_TZ).strip()
    zone = tz(zone_name)
    current = now.astimezone(zone) if now else datetime.now(zone)
    t = norm(raw)

    yearly = _yearly(raw)
    if yearly:
        if 'needs_clarification' in yearly:
            return {'timezone': zone_name, **yearly}
        return {'timezone': zone_name, 'recurrence': yearly, 'next_run_at': compute_next(yearly, int(current.timestamp()), zone_name)}

    monthly = _monthly(raw)
    if monthly:
        return {'timezone': zone_name, 'recurrence': monthly, 'next_run_at': compute_next(monthly, int(current.timestamp()), zone_name)}

    m = re.search(r'\ba cada\s+(\d+)\s*(minuto|minutos|hora|horas|dia|dias)\b', t)
    if m:
        value, unit = max(1, int(m.group(1))), m.group(2)
        minutes = value if 'minuto' in unit else value * 60 if 'hora' in unit else value * 1440
        start, end = _window(raw)
        weekdays = _weekdays(raw)
        recurrence: dict[str, Any] = {'freq': 'interval', 'minutes': minutes}
        if start:
            recurrence['window_start'] = start
        if end:
            recurrence['window_end'] = end
        if weekdays is not None:
            recurrence['weekdays'] = weekdays
        return {'timezone': zone_name, 'recurrence': recurrence, 'next_run_at': compute_next(recurrence, int(current.timestamp()), zone_name)}

    if any(x in t for x in ('todo dia', 'todos os dias', 'diariamente')):
        recurrence = {'freq': 'daily', 'time': _clock(raw)}
        weekdays = _weekdays(raw)
        if weekdays is not None:
            recurrence['weekdays'] = weekdays
        return {'timezone': zone_name, 'recurrence': recurrence, 'next_run_at': compute_next(recurrence, int(current.timestamp()), zone_name)}

    weekdays = _weekdays(raw)
    if weekdays is not None and any(x in t for x in ('toda ', 'todo ', 'cada ', 'segunda a sexta', 'dias uteis', 'fim de semana')):
        recurrence = {'freq': 'weekly', 'weekdays': weekdays, 'time': _clock(raw)}
        return {'timezone': zone_name, 'recurrence': recurrence, 'next_run_at': compute_next(recurrence, int(current.timestamp()), zone_name)}

    once = _relative_once(raw, zone, current)
    if once:
        recurrence = {'freq': 'once', 'at': once.isoformat()}
        return {'timezone': zone_name, 'recurrence': recurrence, 'next_run_at': int(once.timestamp())}

    m = re.search(r'\bdia\s+(\d{1,2})\b', t)
    if m and any(x in t for x in ('lembre', 'agenda', 'agende', 'tenho', 'preciso', 'evento', 'compromisso')):
        day = max(1, min(31, int(m.group(1))))
        hh, mm = map(int, _clock(raw).split(':'))
        year, month = current.year, current.month
        for _ in range(13):
            try:
                candidate = datetime(year, month, day, hh, mm, tzinfo=zone)
            except ValueError:
                candidate = None
            if candidate and candidate > current:
                recurrence = {'freq': 'once', 'at': candidate.isoformat()}
                return {'timezone': zone_name, 'recurrence': recurrence, 'next_run_at': int(candidate.timestamp())}
            month += 1
            if month == 13:
                month = 1
                year += 1
    return None


def extract_alert_offsets(text: str) -> list[int]:
    t = norm(text)
    out: list[int] = []
    for m in re.finditer(r'\b(\d+)\s*(minuto|minutos|hora|horas|dia|dias)\s+antes\b', t):
        value, unit = int(m.group(1)), m.group(2)
        minutes = value if 'minuto' in unit else value * 60 if 'hora' in unit else value * 1440
        if minutes not in out:
            out.append(minutes)
    return sorted(out, reverse=True)


def humanize(recurrence: dict[str, Any]) -> str:
    freq = recurrence.get('freq')
    if freq == 'interval':
        minutes = int(recurrence.get('minutes') or 1)
        cadence = f'a cada {minutes} min' if minutes < 60 or minutes % 60 else f'a cada {minutes // 60} h'
        if recurrence.get('window_start') and recurrence.get('window_end'):
            cadence += f" das {recurrence['window_start']} às {recurrence['window_end']}"
        if recurrence.get('weekdays') == [0, 1, 2, 3, 4]:
            cadence += ' de segunda a sexta'
        return cadence
    if freq == 'daily':
        return f"todos os dias às {recurrence.get('time', '09:00')}"
    if freq == 'weekly':
        return f"semanalmente às {recurrence.get('time', '09:00')}"
    if freq == 'monthly':
        return f"todo dia {recurrence.get('day')} às {recurrence.get('time', '09:00')}"
    if freq == 'yearly':
        return f"todo ano em {int(recurrence.get('day')):02d}/{int(recurrence.get('month')):02d} às {recurrence.get('time', '09:00')}"
    if freq == 'once':
        try:
            return datetime.fromisoformat(str(recurrence.get('at'))).strftime('%d/%m/%Y %H:%M')
        except Exception:
            return str(recurrence.get('at') or 'uma vez')
    return str(recurrence)
