from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from task_manager import list_tasks
from temporal_parser import humanize, norm
from time_store import DEFAULT_TZ, compute_next, list_schedules, tz

_ENTITY_WORDS = {
    'rotina', 'rotinas', 'lembrete', 'lembretes', 'alerta', 'alertas',
    'agenda', 'evento', 'eventos', 'compromisso', 'compromissos',
    'tarefa', 'tarefas', 'task', 'tasks',
}
_MUTATION_STEMS = (
    'cria', 'adicion', 'agenda', 'marca', 'cancel', 'exclu', 'remov', 'apag',
    'paus', 'retom', 'reagend', 'alter', 'mud', 'finaliz', 'conclu', 'termin',
)
_QUERY_TOKENS = {
    'oq', 'oque', 'que', 'qual', 'quais', 'quanto', 'quantos', 'tem', 'temos',
    'tenho', 'falta', 'faltou', 'ficou', 'previsto', 'marcado', 'programado',
}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r'[a-z0-9à-ÿ]+', norm(text)))


def _period(text: str) -> str | None:
    tokens = _tokens(text)
    if 'amanha' in tokens:
        return 'tomorrow'
    if 'hoje' in tokens or 'hj' in tokens:
        return 'today'
    return None


def is_generic_day_query(text: str) -> bool:
    raw = str(text or '').strip()
    if not raw or _period(raw) is None:
        return False
    t = norm(raw)
    if any(stem in t for stem in _MUTATION_STEMS):
        return False
    tokens = _tokens(t)
    if tokens & _ENTITY_WORDS:
        return False
    return '?' in raw or bool(tokens & _QUERY_TOKENS)


def _target_date(period: str):
    today = datetime.now().date()
    return today if period == 'today' else today + timedelta(days=1)


def _clean_schedule_title(item: dict[str, Any]) -> str:
    raw = re.sub(r'\s+', ' ', str(item.get('title') or item.get('message') or 'Lembrete')).strip()
    low = norm(raw)
    if 'agua' in low:
        return '💧 Tomar água'
    raw = re.sub(r'^(?:quero que (?:vc|voce|você) )?me (?:avise|lembre)(?: de)?\s*', '', raw, flags=re.I)
    raw = re.sub(r'\s+(?:minha meta|meta)\s+(?:e|é)?\s*\d+\s*l.*$', '', raw, flags=re.I)
    raw = re.sub(r'\s+(?:a cada|cada)\s+\d+\s+(?:min|minutos?|horas?).*$', '', raw, flags=re.I)
    return (raw.strip(' .,-').capitalize() or 'Lembrete')[:100]


def _occurrence_on(item: dict[str, Any], target_date) -> datetime | None:
    zone = tz(item.get('timezone') or DEFAULT_TZ)
    start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, tzinfo=zone)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    recurrence = item.get('recurrence') or {}
    cursor = int(start.timestamp()) - 1
    for _ in range(120):
        ts = compute_next(recurrence, cursor, item.get('timezone') or DEFAULT_TZ)
        if ts is None:
            return None
        dt = datetime.fromtimestamp(int(ts), zone)
        if dt > end:
            return None
        if dt >= start:
            return dt
        cursor = int(ts)
    return None


def _schedule_lines(period: str) -> list[str]:
    target = _target_date(period)
    rows: list[tuple[datetime, dict[str, Any]]] = []
    for item in list_schedules(status='active', limit=500):
        dt = _occurrence_on(item, target)
        if dt is not None:
            rows.append((dt, item))
    rows.sort(key=lambda x: x[0])

    if not rows:
        return ['📅 Agenda', '- Nada marcado.']

    lines = ['📅 Agenda']
    seen: set[tuple[str, str]] = set()
    for dt, item in rows:
        title = _clean_schedule_title(item)
        recurrence = humanize(item.get('recurrence') or {})
        key = (norm(title), recurrence)
        if key in seen:
            continue
        seen.add(key)
        kind = str(item.get('kind') or '')
        if kind == 'routine':
            lines.append(f'- {title} — {recurrence}')
        else:
            lines.append(f"- {dt.strftime('%H:%M')} — {title}")
        if len(lines) >= 9:
            break
    return lines


def _looks_like_legacy_reminder_task(title: str) -> bool:
    t = norm(title)
    return any(x in t for x in ('me avisa ', 'me avise ', 'me lembra ', 'me lembre '))


def _task_sections(period: str) -> list[str]:
    target = _target_date(period)
    due: list[dict[str, Any]] = []
    overdue: list[dict[str, Any]] = []
    for task in list_tasks(status='todo'):
        if _looks_like_legacy_reminder_task(str(task.get('title') or '')):
            continue
        raw = str(task.get('due') or '').strip()
        if not raw:
            continue
        try:
            day = datetime.fromisoformat(raw).date()
        except Exception:
            continue
        if day == target:
            due.append(task)
        elif period == 'today' and day < target:
            overdue.append(task)

    rank = {'high': 0, 'medium': 1, 'low': 2}
    due.sort(key=lambda x: (rank.get(str(x.get('priority') or 'medium'), 1), str(x.get('due') or '')))
    overdue.sort(key=lambda x: (rank.get(str(x.get('priority') or 'medium'), 1), str(x.get('due') or '')))

    lines: list[str] = []
    if due:
        lines.append('✅ Tarefas')
        for task in due[:6]:
            lines.append(f"- {task.get('title')}")
    if overdue:
        lines.append('⚠️ Atrasadas')
        for task in overdue[:4]:
            lines.append(f"- {task.get('title')}")
    return lines


def overview(period: str = 'today') -> str:
    label = 'hoje' if period == 'today' else 'amanhã'
    sections: list[str] = [f'📌 Seu dia {label}', '']
    sections.extend(_schedule_lines(period))
    task_lines = _task_sections(period)
    if task_lines:
        sections.extend([''] + task_lines)
    return '\n'.join(sections)


def render(text: str) -> str | None:
    if not is_generic_day_query(text):
        return None
    return overview(_period(text) or 'today')
