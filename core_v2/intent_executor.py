from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from conversation_memory import recent
from task_manager import complete_task, list_tasks, update_task
from temporal_parser import norm, parse, tz
from time_store import DEFAULT_TZ, list_schedules, pause, remove, resume, update_schedule


def _short(text: Any, limit: int = 100) -> str:
    value = re.sub(r'\s+', ' ', str(text or '')).strip()
    low = norm(value)
    if 'agua' in low:
        return 'Tomar água'
    value = re.sub(r'^(?:rotina|lembrete|alerta)\s*[-:]\s*', '', value, flags=re.I)
    value = re.sub(r'^(?:quero que (?:vc|você) me avise|me avise|me lembre|lembrar(?:-me)?(?: de)?)\s+', '', value, flags=re.I)
    value = re.sub(r'\s+(?:minha meta|meta)\s+(?:e|é)?\s*\d+\s*l.*$', '', value, flags=re.I)
    value = re.sub(r'\s+(?:a cada|cada)\s+\d+\s+(?:min|minutos?|horas?).*$', '', value, flags=re.I)
    return value.strip(' .,-').capitalize()[:limit] or 'Item'


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
    entity = (entity or 'unknown').casefold()
    if entity == 'routine':
        return {'routine'}
    if entity in {'reminder', 'alert'}:
        # Para o usuário, rotinas que geram avisos também são lembretes.
        return {'reminder', 'alert', 'routine'}
    if entity == 'event':
        return {'event'}
    if entity == 'commitment':
        return {'commitment'}
    if entity == 'schedule':
        return None
    return None


def _tokenize(text: str) -> set[str]:
    stop = {
        'o','a','os','as','de','da','do','das','dos','um','uma','que','me','meu','minha','nossa','nosso',
        'lembrete','lembretes','rotina','rotinas','alerta','alertas','agenda','evento','eventos','compromisso',
        'cancele','cancelar','cancela','remova','remover','pause','pausar','retome','retomar','tarefa','task',
    }
    return {x for x in re.findall(r'[a-z0-9à-ÿ]+', norm(text)) if len(x) >= 2 and x not in stop}


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

    if ids:
        selected: list[dict[str, Any]] = []
        for item in rows:
            iid = str(item.get('id') or '')
            if any(iid.startswith(ref) for ref in ids):
                selected.append(item)
        if selected:
            return selected

    if scope == 'selection':
        context_ids = _ids_from_recent_assistant()
        if context_ids:
            selected = [x for x in rows if any(str(x.get('id') or '').startswith(ref) for ref in context_ids)]
            if selected:
                return selected

    # Filtros estruturados podem restringir a seleção sem voltar ao texto original.
    if filters:
        hour = filters.get('hour')
        if hour is not None:
            try:
                h = int(hour)
                rows = [x for x in rows if datetime.fromtimestamp(int(x.get('next_run_at') or 0), tz(x.get('timezone') or DEFAULT_TZ)).hour == h]
            except Exception:
                pass

    if scope == 'all':
        return rows

    if reference:
        wanted = _tokenize(reference)
        ranked: list[tuple[int, dict[str, Any]]] = []
        for item in rows:
            hay = _tokenize(str(item.get('title') or '') + ' ' + str(item.get('message') or ''))
            overlap = len(wanted & hay)
            score = overlap * 10 + (8 if wanted and wanted <= hay else 0)
            if score:
                ranked.append((score, item))
        ranked.sort(key=lambda x: (x[0], int(x[1].get('created_at') or 0)), reverse=True)
        if ranked:
            best = ranked[0][0]
            return [item for score, item in ranked if score == best]

    return []


def _task_matches(target: dict[str, Any]) -> list[dict[str, Any]]:
    ids = [str(x) for x in (target.get('ids') or []) if x]
    reference = str(target.get('reference') or '').strip()
    scope = str(target.get('scope') or 'unknown').casefold()
    rows = list_tasks(status='todo')
    if ids:
        selected = [x for x in rows if any(str(x.get('id') or '').startswith(ref) for ref in ids)]
        if selected:
            return selected
    if scope == 'all':
        return rows
    if reference:
        wanted = _tokenize(reference)
        ranked: list[tuple[int, dict[str, Any]]] = []
        for item in rows:
            hay = _tokenize(str(item.get('title') or ''))
            overlap = len(wanted & hay)
            score = overlap * 10 + (8 if wanted and wanted <= hay else 0)
            if score:
                ranked.append((score, item))
        ranked.sort(key=lambda x: (x[0], int(x[1].get('updated_at') or 0)), reverse=True)
        if ranked:
            best = ranked[0][0]
            return [item for score, item in ranked if score == best]
    return []


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
        return f"✅ {verb}: {_short(changed[0].get('message') or changed[0].get('title'))}."
    labels: list[str] = []
    for item in changed:
        label = _short(item.get('message') or item.get('title'))
        if label not in labels:
            labels.append(label)
    detail = ', '.join(labels[:4])
    extra = f" e mais {len(labels)-4}" if len(labels) > 4 else ''
    return f"✅ {verb} {len(changed)} itens da sua agenda" + (f": {detail}{extra}." if detail else '.')


def execute(decision: dict[str, Any] | None, original_text: str = '') -> str | None:
    if not decision:
        return None
    route = str(decision.get('route') or '').casefold()
    action = str(decision.get('action') or '').casefold()
    target = decision.get('target') if isinstance(decision.get('target'), dict) else {}

    if route == 'time' and action in {'remove', 'pause', 'resume'}:
        return _apply_schedule_action(action, _schedule_matches(target))

    if route == 'task' and action in {'complete', 'remove'}:
        rows = _task_matches(target)
        if not rows:
            return None
        changed: list[dict[str, Any]] = []
        for item in rows:
            try:
                if action == 'complete':
                    changed.append(complete_task(str(item['id'])))
                else:
                    changed.append(update_task(str(item['id']), status='cancelled', cancelled_at=int(datetime.now().timestamp())))
            except Exception:
                continue
        if not changed:
            return None
        if action == 'complete':
            verb = 'Marquei como concluída'
        else:
            verb = 'Cancelei'
        if len(changed) == 1:
            return f"✅ {verb}: {changed[0].get('title')}."
        return f"✅ {verb} {len(changed)} tarefas."

    if route == 'task' and action == 'reschedule':
        rows = _task_matches(target)
        if len(rows) != 1:
            return None
        standalone = str(decision.get('standalone_request') or original_text)
        parsed = parse(standalone)
        if not parsed or not parsed.get('next_run_at'):
            return None
        zone = tz(parsed.get('timezone') or DEFAULT_TZ)
        due = datetime.fromtimestamp(int(parsed['next_run_at']), zone).isoformat()
        updated = update_task(str(rows[0]['id']), due=due, status='todo')
        pretty = datetime.fromisoformat(due).strftime('%d/%m/%Y %H:%M')
        return f"📅 Reagendei {updated.get('title')} para {pretty}."

    return None
