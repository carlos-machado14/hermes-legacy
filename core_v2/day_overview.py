from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from task_manager import list_tasks
from time_store import DEFAULT_TZ, compute_next, list_schedules, tz


def _schedule_label(item: dict[str, Any]) -> str:
    metadata = item.get('metadata') if isinstance(item.get('metadata'), dict) else {}
    raw = str(metadata.get('display_label') or item.get('title') or item.get('message') or 'Item')
    raw = re.sub(r'\s+', ' ', raw).strip()
    if ' - ' in raw:
        prefix, suffix = raw.split(' - ', 1)
        if len(prefix) <= 20 and suffix.strip():
            raw = suffix.strip()
    return raw[:100]


def _occurrence_on(item: dict[str, Any], target_date: date) -> datetime | None:
    zone = tz(item.get('timezone') or DEFAULT_TZ)
    start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, tzinfo=zone)
    end = start + timedelta(days=1)
    cursor = int(start.timestamp()) - 1
    for _ in range(300):
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


def _schedule_rows(start: date, end: date) -> list[tuple[datetime, dict[str, Any]]]:
    rows: list[tuple[datetime, dict[str, Any]]] = []
    schedules = list_schedules(status='active', limit=500)
    day = start
    while day <= end:
        for item in schedules:
            dt = _occurrence_on(item, day)
            if dt is not None:
                rows.append((dt, item))
        day += timedelta(days=1)
    rows.sort(key=lambda pair: pair[0])
    return rows


def _task_rows(start: date, end: date, *, include_overdue: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
        if start <= day <= end:
            due.append(task)
        elif include_overdue and day < start:
            overdue.append(task)

    rank = {'high': 0, 'medium': 1, 'low': 2}
    due.sort(key=lambda x: (str(x.get('due') or ''), rank.get(str(x.get('priority') or 'medium'), 1)))
    overdue.sort(key=lambda x: (rank.get(str(x.get('priority') or 'medium'), 1), str(x.get('due') or '')))
    return due, overdue


def overview_range(start: date, end: date, label: str | None = None) -> str:
    if end < start:
        start, end = end, start
    single_day = start == end
    if not label:
        label = start.strftime('%d/%m/%Y') if single_day else f'{start:%d/%m} a {end:%d/%m/%Y}'

    sections: list[str] = [f'📌 Agenda — {label}', '']
    rows = _schedule_rows(start, end)

    if not rows:
        sections.extend(['📅 Compromissos', '- Nada marcado.'])
    else:
        sections.append('📅 Compromissos')
        seen: set[tuple[str, date]] = set()
        shown = 0
        for dt, item in rows:
            identity = str(item.get('id') or '')
            key = (identity, dt.date())
            if key in seen:
                continue
            seen.add(key)
            prefix = dt.strftime('%H:%M') if single_day else dt.strftime('%d/%m %H:%M')
            sections.append(f'- {prefix} — {_schedule_label(item)}')
            shown += 1
            if shown >= 20:
                sections.append('- … mais itens não exibidos')
                break

    today = datetime.now(tz(DEFAULT_TZ)).date()
    due, overdue = _task_rows(start, end, include_overdue=single_day and start == today)
    if due:
        sections.extend(['', '✅ Tarefas'])
        for task in due[:12]:
            raw_due = str(task.get('due') or '')
            try:
                task_day = datetime.fromisoformat(raw_due).date()
                prefix = '' if single_day else f'{task_day:%d/%m} — '
            except Exception:
                prefix = ''
            sections.append(f"- {prefix}{task.get('title')} [ID {task.get('id')}]")
    if overdue:
        sections.extend(['', '⚠️ Atrasadas'])
        for task in overdue[:6]:
            sections.append(f"- {task.get('title')} [ID {task.get('id')}]")

    return '\n'.join(sections)


def overview(period: str = 'today') -> str:
    today = datetime.now(tz(DEFAULT_TZ)).date()
    if period == 'tomorrow':
        target = today + timedelta(days=1)
        return overview_range(target, target, 'amanhã')
    return overview_range(today, today, 'hoje')
