from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from conversation_memory import recent
from day_overview import overview_range
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


def _occurs_on(item: dict[str, Any], target_date: date) -> datetime | None:
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


def _date_range(filters: dict[str, Any]) -> tuple[date | None, date | None, str]:
    zone = tz(DEFAULT_TZ)
    today = datetime.now(zone).date()
    raw_date = str(filters.get('date') or '').strip()
    if raw_date:
        try:
            target = datetime.fromisoformat(raw_date).date()
            return target, target, target.strftime('%d/%m/%Y')
        except Exception:
            pass

    raw_start = str(filters.get('date_start') or '').strip()
    raw_end = str(filters.get('date_end') or '').strip()
    if raw_start and raw_end:
        try:
            start = datetime.fromisoformat(raw_start).date()
            end = datetime.fromisoformat(raw_end).date()
            return start, end, f'{start:%d/%m} a {end:%d/%m/%Y}'
        except Exception:
            pass

    period = str(filters.get('period') or '').casefold()
    if period == 'today':
        return today, today, 'hoje'
    if period == 'tomorrow':
        target = today + timedelta(days=1)
        return target, target, 'amanhã'
    return None, None, period


def _filter_schedules(rows: list[dict[str, Any]], target: dict[str, Any]) -> list[dict[str, Any]]:
    filters = target.get('filters') if isinstance(target.get('filters'), dict) else {}
    start, end, _label_text = _date_range(filters)
    hour = filters.get('hour')
    minute = filters.get('minute')

    if start is not None and end is not None:
        filtered: list[dict[str, Any]] = []
        day_count = min(62, max(1, (end - start).days + 1))
        for item in rows:
            matched = False
            for offset in range(day_count):
                occurrence = _occurs_on(item, start + timedelta(days=offset))
                if occurrence is None:
                    continue
                if hour is not None:
                    try:
                        hh = int(hour)
                        mm = int(minute) if minute is not None else None
                        if occurrence.hour != hh or (mm is not None and occurrence.minute != mm):
                            continue
                    except Exception:
                        pass
                matched = True
                break
            if matched:
                filtered.append(item)
        return filtered

    if hour is not None:
        filtered = []
        for item in rows:
            next_run = item.get('next_run_at')
            if not next_run:
                continue
            try:
                dt = datetime.fromtimestamp(int(next_run), tz(item.get('timezone') or DEFAULT_TZ))
                hh = int(hour)
                mm = int(minute) if minute is not None else None
                if dt.hour == hh and (mm is None or dt.minute == mm):
                    filtered.append(item)
            except Exception:
                continue
        rows = filtered
    return rows


def _schedule_matches(target: dict[str, Any]) -> list[dict[str, Any]]:
    scope = str(target.get('scope') or 'unknown').casefold()
    entity = str(target.get('entity') or 'unknown').casefold()
    ids = [str(x) for x in (target.get('ids') or []) if x]
    reference = str(target.get('reference') or '').strip()
    filters = target.get('filters') if isinstance(target.get('filters'), dict) else {}

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

    # Quando a intenção já foi classificada semanticamente como filtrada e existe
    # um filtro objetivo de data/horário, o filtro local é suficiente para seleção.
    if scope == 'filtered' and filters:
        return rows
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


def _list_schedules(target: dict[str, Any]) -> str:
    rows = _schedule_matches({**target, 'scope': 'all' if target.get('scope') == 'unknown' else target.get('scope')})
    filters = target.get('filters') if isinstance(target.get('filters'), dict) else {}
    start, end, label = _date_range(filters)
    if start is not None and end is not None:
        return overview_range(start, end, label)
    if not rows:
        return 'Não há itens ativos na agenda.'
    lines = ['📅 Agenda ativa']
    for item in rows[:30]:
        lines.append(f"- {_label(item)} — {humanize(item.get('recurrence') or {})} [ID {item.get('id')}]")
    return '\n'.join(lines)


def _list_tasks(target: dict[str, Any]) -> str:
    filters = target.get('filters') if isinstance(target.get('filters'), dict) else {}
    start, end, label = _date_range(filters)
    rows = list_tasks(status='todo')
    if start is not None and end is not None:
        selected: list[dict[str, Any]] = []
        for item in rows:
            due = str(item.get('due') or '').strip()
            if not due:
                continue
            try:
                due_date = datetime.fromisoformat(due).date()
                if start <= due_date <= end:
                    selected.append(item)
            except Exception:
                continue
        rows = selected
    if not rows:
        return f'Nenhuma tarefa para {label}.' if start is not None else 'Nenhuma tarefa pendente.'
    lines = [f'✅ Tarefas — {label}' if start is not None else '✅ Tarefas pendentes']
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
    title = str(target.get('reference') or '').strip() or str(original_text or '').strip()
    if not title:
        return None
    due = None
    parsed = parse(str(decision.get('standalone_request') or original_text)) or parse(original_text)
    if parsed and parsed.get('next_run_at'):
        due = datetime.fromtimestamp(int(parsed['next_run_at']), tz(parsed.get('timezone') or DEFAULT_TZ)).isoformat()
    task = create_task(title[:180], due=due, kind='action', metadata={'semantic_source': True})
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
        start, end, label = _date_range(filters)
        if start is None or end is None:
            today = datetime.now(tz(DEFAULT_TZ)).date()
            start = end = today
            label = 'hoje'
        return overview_range(start, end, label)

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
