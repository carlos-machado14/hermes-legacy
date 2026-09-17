from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from task_manager import list_tasks
from temporal_parser import humanize
from time_store import DEFAULT_TZ, compute_next, list_schedules, tz


def _target_date(period: str):
    today = datetime.now(tz(DEFAULT_TZ)).date()
    return today if period == 'today' else today + timedelta(days=1)


def _schedule_label(item: dict[str, Any]) -> str:
    metadata = item.get('metadata') if isinstance(item.get('metadata'), dict) else {}
    raw = str(metadata.get('display_label') or item.get('title') or item.get('message') or 'Item')
    raw = re.sub(r'\s+', ' ', raw).strip()
    if ' - ' in raw:
        prefix, suffix = raw.split(' - ', 1)
        if len(prefix) <= 20 and suffix.strip():
            raw = suffix.strip()
    return raw[:100]


def _occurrence_on(item: dict[str, Any], target_date) -> datetime | None:
    zone = tz(item.get('timezone') or DEFAULT_TZ)
    start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, tzinfo=zone)
    end = start + timedelta(days=1)
    cursor = int(start.timestamp()) - 1
    for _ in range(200):
        ts = compute_next(item.get('recurrence') or {}, cursor, item.get('timezone') or DEFAULT_TZ)
        if ts is None:
            return None
        dt = datetime.fromtimestamp(int(ts), zone)
        if dt >= end:
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
    rows.sort(key=lambda pair: pair[0])

    if not rows:
        return ['📅 Agenda', '- Nada marcado.']

    lines = ['📅 Agenda']
    seen: set[str] = set()
    for dt, item in rows:
        identity = str(item.get('id') or '')
        if identity in seen:
            continue
        seen.add(identity)
        recurrence = item.get('recurrence') or {}
        if recurrence.get('freq') == 'once':
            lines.append(f"- {dt.strftime('%H:%M')} — {_schedule_label(item)}")
        else:
            lines.append(f"- {_schedule_label(item)} — {humanize(recurrence)}")
        if len(lines) >= 10:
            break
    return lines


def _task_sections(period: str) -> list[str]:
    target = _target_date(period)
    due: list[dict[str, Any]] = []
    overdue: list[dict[str, Any]] = []
    for task in list_tasks(status='todo'):
        if str(task.get('kind') or 'action') != 'action':
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
            lines.append(f"- {task.get('title')} [ID {task.get('id')}]")
    if overdue:
        lines.append('⚠️ Atrasadas')
        for task in overdue[:4]:
            lines.append(f"- {task.get('title')} [ID {task.get('id')}]")
    return lines


def overview(period: str = 'today') -> str:
    normalized = 'tomorrow' if period == 'tomorrow' else 'today'
    label = 'amanhã' if normalized == 'tomorrow' else 'hoje'
    sections: list[str] = [f'📌 Seu dia {label}', '']
    sections.extend(_schedule_lines(normalized))
    task_lines = _task_sections(normalized)
    if task_lines:
        sections.extend([''] + task_lines)
    return '\n'.join(sections)
