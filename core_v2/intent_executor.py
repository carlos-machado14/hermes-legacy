from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from conversation_memory import recent
from day_overview import overview as day_overview
from task_manager import complete_task, create_task, list_tasks, update_task
from temporal_parser import humanize, parse, tz
from time_store import (
    DEFAULT_TZ,
    compute_next,
    create_schedule,
    list_schedules,
    pause,
    remove,
    resume,
    update_schedule,
)


def _label(item: dict[str, Any], limit: int = 100) -> str:
    metadata = item.get('metadata') if isinstance(item.get('metadata'), dict) else {}
    value = str(metadata.get('display_label') or item.get('title') or item.get('message') or 'Item')
    value = re.sub(r'\s+', ' ', value).strip()
    if ' - ' in value:
        prefix, suffix = value.split(' - ', 1)
        if len(prefix) <= 20 and suffix.strip():
            value = suffix.strip()
    return value[:limit]


def _ids_from_recent_assistant() -> list[str]:
    for row in reversed(list(recent(limit=20))):
        if row.get('role') != 'assistant':
            continue
        ids = re.findall(r'\b(?:ID\s*)?([0-9a-f]{8,32})\b', str(row.get('text') or ''), re.I)
        out: list[str] = []
        for ref in ids:
            if ref not in out:
                out.append(ref)
        if out:
            return out
    return []


def _entity_kinds(entity: str) -> set[str] | None:
    mapping = {
        'routine': {'routine'},
        'reminder': {'reminder', 'alert', 'routine'},
        'alert': {'alert'},
        'event': {'event'},
        'commitment': {'commitment'},
        'schedule': None,
        'day': None,
        'unknown': None,
    }
    return mapping.get((entity or 'unknown').casefold())


def _similarity(reference: str, item: dict[str, Any]) -> float:
    wanted = re.sub(r'\s+', ' ', reference.casefold()).strip()
    if not wanted:
        return 0.0
    candidates = [
        str(item.get('title') or '').casefold(),
        str(item.get('message') or '').casefold(),
        _label(item).casefold(),
    ]
    score = 0.0
    for candidate in candidates:
        candidate = re.sub(r'\s+', ' ', candidate).strip()
        if not candidate:
            continue
        if wanted == candidate:
            return 1.0
        if wanted in candidate or candidate in wanted:
            score = max(score, 0.92)
        score = max(score, SequenceMatcher(None, wanted, candidate).ratio())
    return score


def _filter_schedules(rows: list[dict[str, Any]], target: dict[str, Any]) -> list[dict[str, Any]]:
    filters = target.get('filters') if isinstance(target.get('filters'), dict) else {}
    hour = filters.get('hour')
    minute = filters.get('minute')
    if hour is not None:
        try:
            hh = int(hour)
            mm = int(minute) if minute is not None else None
            filtered: list[dict[str, Any]] = []
            for item in rows:
                next_run = item.get('next_run_at')
                if not next_run:
                    continue
                dt = datetime.fromtimestamp(int(next_run), tz(item.get('timezone') or DEFAULT_TZ))
                if dt.hour == hh and (mm is None or dt.minute == mm):
                    filtered.append(item)
            rows = filtered
        except Exception:
            pass
    return rows


def _schedule_matches(target: dict[str, Any]) -> list[dict[str, Any]]:
    scope = str(target.get('scope') or 'unknown').casefold()
    entity = str(target.get('entity') or 'unknown').casefold()
    ids = [str(x) for x in (target.get('ids') or []) if x]
    reference = str(target.get('reference') or '').strip()

    rows = list_schedules(status='active', limit=1000)
    kinds = _entity_kinds(entity)
    if kinds is not None:
        rows = [x for x in rows if str(x.get('kind') or 'reminder') in kinds]
    rows = _filter_schedules(rows, target)

    if ids:
        selected = [x for x in rows if any(str(x.get('id') or '').startswith(ref) for ref in ids)]
        if selected:
            return selected

    if scope == 'selection':
        context_ids = _ids_from_recent_assistant()
        selected = [x for x in rows if any(str(x.get('id') or '').startswith(ref) for ref in context_ids)]
        if selected:
            return selected

    if scope == 'all':
        return rows

    if reference:
        ranked = sorted(((_similarity(reference, item), item) for item in rows), key=lambda pair: pair[0], reverse=True)
        if ranked and ranked[0][0] >= 0.55:
            best = ranked[0][0]
            return [item for score, item in ranked if score >= max(0.55, best - 0.03)]
    return []


def _task_matches(target: dict[str, Any]) -> list[dict[str, Any]]:
    scope = str(target.get('scope') or 'unknown').casefold()
    ids = [str(x) for x in (target.get('ids') or []) if x]
    reference = str(target.get('reference') or '').strip()
    rows = list_tasks(status='todo')

    if ids:
        selected = [x for x in rows if any(str(x.get('id') or '').startswith(ref) for ref in ids)]
        if selected:
            return selected
    if scope == 'all':
        return rows
    if reference:
        ranked = sorted(((_similarity(reference, item), item) for item in rows), key=lambda pair: pair[0], reverse=True)
        if ranked and ranked[0][0] >= 0.55:
            best = ranked[0][0]
            return [item for score, item in ranked if score >= max(0.55, best - 0.03)]
    return []


def _target_day(filters: dict[str, Any]) -> tuple[datetime.date | None, str]:
    zone = tz(DEFAULT_TZ)
    today = datetime.now(zone).date()
    period = str(filters.get('period') or '').casefold()
    raw_date = str(filters.get('date') or '').strip()
    if raw_date:
        try:
            return datetime.fromisoformat(raw_date).date(), raw_date
        except Exception:
            pass
    if period == 'tomorrow':
        return today + timedelta(days=1), 'amanhã'
    if period == 'today' or not period:
        return today, 'hoje'
    return None, period


def _occurs_on(item: dict[str, Any], target_date) -> datetime | None:
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


def _list_schedules(target: dict[str, Any]) -> str:
    rows = _schedule_matches({**target, 'scope': 'all' if target.get('scope') == 'unknown' else target.get('scope')})
    filters = target.get('filters') if isinstance(target.get('filters'), dict) else {}
    target_date, label = _target_day(filters)
    listed: list[tuple[datetime | None, dict[str, Any]]] = []
    for item in rows:
        occurrence = _occurs_on(item, target_date) if target_date else None
        if target_date and occurrence is None:
            continue
        listed.append((occurrence, item))
    listed.sort(key=lambda pair: pair[0] or datetime.max.replace(tzinfo=tz(DEFAULT_TZ)))
    if not listed:
        return f'Não há itens ativos para {label}.' if target_date else 'Não há itens ativos na agenda.'
    lines = [f'📅 Agenda — {label}' if target_date else '📅 Agenda ativa']
    seen: set[str] = set()
    for occurrence, item in listed[:30]:
        key = str(item.get('id') or '')
        if key in seen:
            continue
        seen.add(key)
        recurrence = item.get('recurrence') or {}
        when = humanize(recurrence)
        time_text = occurrence.strftime('%H:%M') if occurrence else ''
        prefix = f'{time_text} — ' if time_text and recurrence.get('freq') == 'once' else ''
        lines.append(f"- {prefix}{_label(item)} — {when} [ID {item.get('id')}]")
    return '\n'.join(lines)


def _list_tasks(target: dict[str, Any]) -> str:
    filters = target.get('filters') if isinstance(target.get('filters'), dict) else {}
    target_date, label = _target_day(filters)
    rows = list_tasks(status='todo')
    if target_date:
        selected: list[dict[str, Any]] = []
        for item in rows:
            due = str(item.get('due') or '').strip()
            if not due:
                continue
            try:
                if datetime.fromisoformat(due).date() == target_date:
                    selected.append(item)
            except Exception:
                continue
        rows = selected
    if not rows:
        return f'Nenhuma tarefa para {label}.' if target_date else 'Nenhuma tarefa pendente.'
    lines = [f'✅ Tarefas — {label}' if target_date else '✅ Tarefas pendentes']
    for item in rows[:30]:
        lines.append(f"- {item.get('title')} [ID {item.get('id')}]")
    return '\n'.join(lines)


def _create_schedule_from_decision(decision: dict[str, Any], original_text: str) -> str | None:
    target = decision.get('target') if isinstance(decision.get('target'), dict) else {}
    parsed = parse(str(decision.get('standalone_request') or original_text)) or parse(original_text)
    if not parsed or not parsed.get('recurrence'):
        return None
    if parsed.get('needs_clarification'):
        return str(parsed.get('needs_clarification'))
    entity = str(target.get('entity') or 'reminder').casefold()
    kind = entity if entity in {'routine', 'reminder', 'alert', 'event', 'commitment'} else 'reminder'
    message = str(target.get('reference') or '').strip() or str(decision.get('standalone_request') or original_text).strip()
    title = message[:120]
    metadata = {'display_label': message[:120], 'semantic_source': True}
    item = create_schedule(
        title,
        message,
        parsed['recurrence'],
        kind=kind,
        timezone=parsed.get('timezone') or DEFAULT_TZ,
        metadata=metadata,
    )
    next_text = 'sem próxima execução'
    if item.get('next_run_at'):
        dt = datetime.fromtimestamp(int(item['next_run_at']), tz(item.get('timezone') or DEFAULT_TZ))
        next_text = dt.strftime('%d/%m/%Y %H:%M')
    return f"✅ Salvei: {message}\nAgenda: {humanize(item.get('recurrence') or {})}\nPróximo: {next_text}\nID: {item.get('id')}"


def _create_task_from_decision(decision: dict[str, Any], original_text: str) -> str | None:
    target = decision.get('target') if isinstance(decision.get('target'), dict) else {}
    title = str(target.get('reference') or '').strip()
    if not title:
        return None
    due = None
    parsed = parse(str(decision.get('standalone_request') or original_text)) or parse(original_text)
    if parsed and parsed.get('next_run_at'):
        due = datetime.fromtimestamp(int(parsed['next_run_at']), tz(parsed.get('timezone') or DEFAULT_TZ)).isoformat()
    task = create_task(title, due=due, kind='action', metadata={'semantic_source': True})
    return f"✅ Criei a tarefa: {task.get('title')} [ID {task.get('id')}]"


def _apply_schedule_action(action: str, rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    changed: list[dict[str, Any]] = []
    for item in rows:
        try:
            if action == 'remove':
                changed.append(remove(str(item['id'])))
            elif action == 'pause':
                changed.append(pause(str(item['id'])))
            elif action == 'resume':
                changed.append(resume(str(item['id'])))
        except Exception:
            continue
    if not changed:
        return None
    verb = {'remove': 'Cancelei', 'pause': 'Pausei', 'resume': 'Retomei'}[action]
    if len(changed) == 1:
        return f"✅ {verb}: {_label(changed[0])}."
    return f"✅ {verb} {len(changed)} itens."


def _reschedule_schedule(decision: dict[str, Any], original_text: str) -> str | None:
    target = decision.get('target') if isinstance(decision.get('target'), dict) else {}
    rows = _schedule_matches(target)
    if len(rows) != 1:
        return None
    parsed = parse(str(decision.get('standalone_request') or original_text)) or parse(original_text)
    if not parsed or not parsed.get('recurrence'):
        return None
    updated = update_schedule(str(rows[0]['id']), recurrence=parsed['recurrence'], timezone=parsed.get('timezone') or rows[0].get('timezone') or DEFAULT_TZ)
    return f"📅 Reagendei {_label(updated)} para {humanize(updated.get('recurrence') or {})}."


def _apply_task_action(action: str, target: dict[str, Any]) -> str | None:
    rows = _task_matches(target)
    if not rows:
        return None
    changed: list[dict[str, Any]] = []
    for item in rows:
        try:
            if action == 'complete':
                changed.append(complete_task(str(item['id'])))
            elif action == 'remove':
                changed.append(update_task(str(item['id']), status='cancelled', cancelled_at=int(datetime.now().timestamp())))
        except Exception:
            continue
    if not changed:
        return None
    if len(changed) == 1:
        verb = 'Marquei como concluída' if action == 'complete' else 'Cancelei'
        return f"✅ {verb}: {changed[0].get('title')}."
    verb = 'Concluí' if action == 'complete' else 'Cancelei'
    return f"✅ {verb} {len(changed)} tarefas."


def _reschedule_task(decision: dict[str, Any], original_text: str) -> str | None:
    target = decision.get('target') if isinstance(decision.get('target'), dict) else {}
    rows = _task_matches(target)
    if len(rows) != 1:
        return None
    parsed = parse(str(decision.get('standalone_request') or original_text)) or parse(original_text)
    if not parsed or not parsed.get('next_run_at'):
        return None
    zone = tz(parsed.get('timezone') or DEFAULT_TZ)
    due = datetime.fromtimestamp(int(parsed['next_run_at']), zone).isoformat()
    updated = update_task(str(rows[0]['id']), due=due, status='todo')
    return f"📅 Reagendei {updated.get('title')} para {datetime.fromisoformat(due).strftime('%d/%m/%Y %H:%M')}."


def execute(decision: dict[str, Any] | None, original_text: str = '') -> str | None:
    if not decision:
        return None
    route = str(decision.get('route') or '').casefold()
    action = str(decision.get('action') or '').casefold()
    target = decision.get('target') if isinstance(decision.get('target'), dict) else {}
    entity = str(target.get('entity') or 'unknown').casefold()

    if entity == 'day' and action in {'list', 'status', 'answer'}:
        filters = target.get('filters') if isinstance(target.get('filters'), dict) else {}
        period = str(filters.get('period') or 'today').casefold()
        return day_overview('tomorrow' if period == 'tomorrow' else 'today')

    if route == 'time':
        if action == 'create':
            return _create_schedule_from_decision(decision, original_text)
        if action in {'list', 'status'}:
            return _list_schedules(target)
        if action in {'remove', 'pause', 'resume'}:
            return _apply_schedule_action(action, _schedule_matches(target))
        if action == 'reschedule':
            return _reschedule_schedule(decision, original_text)

    if route == 'task':
        if action == 'create':
            return _create_task_from_decision(decision, original_text)
        if action in {'list', 'status'}:
            return _list_tasks(target)
        if action in {'complete', 'remove'}:
            return _apply_task_action(action, target)
        if action == 'reschedule':
            return _reschedule_task(decision, original_text)

    return None
