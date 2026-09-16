from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from temporal_parser import humanize, norm
from time_store import DEFAULT_TZ, compute_next, list_schedules, tz

_QUERY_WORDS = (
    'qual ', 'quais ', 'quantos ', 'quantas ', 'o que ', 'que temos', 'que tenho',
    'tenho ', 'temos ', 'tem algum', 'tem alguma', 'existe ', 'existem ',
    'lista ', 'liste ', 'mostra ', 'mostre ', 'me diga ',
)
_SCHEDULE_WORDS = (
    'rotina', 'rotinas', 'lembrete', 'lembretes', 'alerta', 'alertas',
    'agenda', 'evento', 'eventos', 'compromisso', 'compromissos', 'horario', 'horários', 'horarios',
)
_MUTATION_WORDS = (
    'cria ', 'crie ', 'adiciona ', 'adicione ', 'agenda ', 'agende ', 'marca ', 'marque ',
    'cancela ', 'cancele ', 'remove ', 'remova ', 'apaga ', 'apague ', 'pausa ', 'pause ',
    'retoma ', 'retome ', 'muda ', 'mude ', 'altera ', 'altere ', 'reagenda ', 'reagende ',
    'me avisa', 'me avise', 'me lembre',
)


def _is_read_query(text: str) -> bool:
    t = norm(text)
    if any(word in t for word in _MUTATION_WORDS):
        return False
    if not any(word in t for word in _SCHEDULE_WORDS):
        return False
    return '?' in text or any(word in t for word in _QUERY_WORDS)


def _clock(text: str) -> tuple[int, int] | None:
    t = norm(text)
    patterns = (
        r'\b(?:as|a)\s*(\d{1,2})(?::(\d{2}))?\s*h?\b',
        r'\b(\d{1,2}):(\d{2})\b',
        r'\b(\d{1,2})h(?:(\d{2}))?\b',
    )
    for pattern in patterns:
        matches = list(re.finditer(pattern, t))
        if not matches:
            continue
        m = matches[-1]
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    return None


def _window(text: str) -> tuple[datetime, datetime, str]:
    t = norm(text)
    zone = tz(DEFAULT_TZ)
    now = datetime.now(zone)
    if 'amanha' in t:
        start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1) - timedelta(seconds=1), 'amanhã'
    if any(x in t for x in ('semana', '7 dias', 'proximos dias')):
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=7) - timedelta(seconds=1), 'nos próximos 7 dias'
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1) - timedelta(seconds=1), 'hoje'


def _kinds(text: str) -> set[str] | None:
    t = norm(text)
    if 'rotina' in t:
        return {'routine'}
    if 'evento' in t:
        return {'event'}
    if 'compromisso' in t:
        return {'commitment'}
    if 'alerta' in t:
        return {'alert'}
    if 'lembrete' in t:
        return {'reminder', 'alert'}
    return None


def _occurs(item: dict[str, Any], start: datetime, end: datetime, clock: tuple[int, int] | None) -> datetime | None:
    recurrence = item.get('recurrence') or {}
    zone = tz(item.get('timezone') or DEFAULT_TZ)
    cursor = int(start.astimezone(zone).timestamp()) - 1
    for _ in range(100):
        ts = compute_next(recurrence, cursor, item.get('timezone') or DEFAULT_TZ)
        if ts is None:
            return None
        dt = datetime.fromtimestamp(int(ts), zone)
        if dt > end.astimezone(zone):
            return None
        if dt >= start.astimezone(zone):
            if clock is None or (dt.hour, dt.minute) == clock:
                return dt
        cursor = int(ts)
    return None


def _display_message(item: dict[str, Any]) -> str:
    raw = re.sub(r'\s+', ' ', str(item.get('message') or item.get('title') or 'Lembrete')).strip()
    low = norm(raw)
    if 'agua' in low:
        return 'Tomar água'
    raw = re.sub(r'\s+(?:minha meta|meta)\s+(?:e|é)?\s*\d+\s*l.*$', '', raw, flags=re.I)
    raw = re.sub(r'\s+(?:a cada|cada)\s+\d+\s+(?:min|minutos?|horas?).*$', '', raw, flags=re.I)
    raw = re.sub(r'^(?:para\s+)?(?:me\s+)?lembrar(?:-me)?\s+(?:de\s+)?', '', raw, flags=re.I)
    return raw.strip(' .,-').capitalize()[:120] or 'Lembrete'


def handle(text: str) -> str | None:
    raw = str(text or '').strip()
    if not raw or not _is_read_query(raw):
        return None

    start, end, period_label = _window(raw)
    wanted_clock = _clock(raw)
    wanted_kinds = _kinds(raw)
    matches: list[tuple[datetime, dict[str, Any]]] = []

    for item in list_schedules(status='active', limit=500):
        kind = str(item.get('kind') or 'reminder')
        if wanted_kinds is not None and kind not in wanted_kinds:
            continue
        occurrence = _occurs(item, start, end, wanted_clock)
        if occurrence is not None:
            matches.append((occurrence, item))

    matches.sort(key=lambda pair: (pair[0], str(pair[1].get('id') or '')))
    clock_label = f" às {wanted_clock[0]:02d}:{wanted_clock[1]:02d}" if wanted_clock else ''

    if not matches:
        noun = 'rotinas' if wanted_kinds == {'routine'} else 'itens na agenda'
        return f'Não encontrei {noun} {period_label}{clock_label}.'

    if wanted_kinds == {'routine'}:
        title = f'🔁 Rotinas {period_label}{clock_label}'
    else:
        title = f'📅 Agenda {period_label}{clock_label}'

    lines = [title]
    seen: set[str] = set()
    for dt, item in matches:
        item_id = str(item.get('id') or '')
        if item_id in seen:
            continue
        seen.add(item_id)
        message = _display_message(item)
        recurrence = humanize(item.get('recurrence') or {})
        if wanted_clock:
            lines.append(f'- {message} — {recurrence}')
        else:
            lines.append(f"- {dt.strftime('%H:%M')} — {message} — {recurrence}")
        if len(lines) >= 16:
            break
    return '\n'.join(lines)
