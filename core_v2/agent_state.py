#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from decision_log import recent as recent_decisions
from goal_manager import list_goals
from task_manager import list_tasks
from time_store import list_schedules

ROOT = Path.home() / '.hermes/core-v2'
STATE_DIR = ROOT / 'state'
STATE_FILE = STATE_DIR / 'agent_state.json'


def _read() -> dict[str, Any]:
    try:
        data = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write(data: dict[str, Any]) -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(STATE_FILE)
    return data


def _due_bucket(tasks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    today = datetime.now().date()
    today_rows: list[dict[str, Any]] = []
    overdue: list[dict[str, Any]] = []
    later: list[dict[str, Any]] = []
    for task in tasks:
        raw = str(task.get('due') or '').strip()
        if not raw:
            later.append(task)
            continue
        try:
            due = datetime.fromisoformat(raw).date()
        except Exception:
            later.append(task)
            continue
        if due < today:
            overdue.append(task)
        elif due == today:
            today_rows.append(task)
        else:
            later.append(task)
    return today_rows, overdue, later


def _priority(task: dict[str, Any]) -> tuple[int, int]:
    rank = {'high': 0, 'medium': 1, 'low': 2}
    return rank.get(str(task.get('priority') or 'medium'), 1), int(task.get('created_at') or 0)


def _schedule_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows[:40]:
        out.append({
            'id': row.get('id'),
            'kind': row.get('kind'),
            'title': row.get('title') or row.get('message'),
            'next_at': row.get('next_at'),
            'timezone': row.get('timezone'),
        })
    return out


def refresh(*, current_context: str | None = None, recent_result: str | None = None, pending_decision: str | None = None) -> dict[str, Any]:
    previous = _read()
    goals = list_goals(include_done=False)
    tasks = sorted(list_tasks(status='todo'), key=_priority)
    due_today, overdue, later = _due_bucket(tasks)
    schedules = list_schedules(status='active', limit=200)
    decisions = recent_decisions(30)

    primary_goal = None
    if goals:
        money = [g for g in goals if g.get('category') == 'money']
        primary_goal = (money or goals)[-1]

    next_actions = (due_today + overdue + later)[:5]
    open_loops: list[dict[str, Any]] = []
    for task in (overdue + due_today)[:10]:
        open_loops.append({
            'type': 'task',
            'id': task.get('id'),
            'title': task.get('title'),
            'status': 'overdue' if task in overdue else 'due_today',
        })
    for row in decisions[-10:]:
        if row.get('kind') in {'approval_requested', 'pending_decision', 'action_failed'}:
            open_loops.append({
                'type': row.get('kind'),
                'title': row.get('summary'),
                'ts': row.get('ts'),
            })

    recent_results = list(previous.get('recent_results') or [])
    if recent_result:
        recent_results.append({'ts': int(time.time()), 'text': str(recent_result)[:1400]})
    recent_results = recent_results[-8:]

    pending = list(previous.get('pending_decisions') or [])
    if pending_decision:
        pending.append({'ts': int(time.time()), 'text': str(pending_decision)[:700]})
    pending = pending[-8:]

    state = {
        'version': 1,
        'updated_at': int(time.time()),
        'current_context': (current_context if current_context is not None else previous.get('current_context')) or '',
        'active_goals': goals[:10],
        'primary_goal': primary_goal,
        'today': {
            'tasks_due': len(due_today),
            'tasks_overdue': len(overdue),
            'tasks_open': len(tasks),
            'active_schedules': len(schedules),
        },
        'open_loops': open_loops[:15],
        'next_actions': next_actions,
        'pending_decisions': pending,
        'recent_results': recent_results,
        'active_schedules': _schedule_summary(schedules),
    }
    return _write(state)


def get(*, refresh_state: bool = False) -> dict[str, Any]:
    if refresh_state or not STATE_FILE.exists():
        return refresh()
    return _read()


def compact(max_actions: int = 4) -> str:
    state = get(refresh_state=True)
    out = ['ESTADO OPERACIONAL DO AGENTE']
    ctx = str(state.get('current_context') or '').strip()
    if ctx:
        out.append('Contexto atual: ' + ctx[:700])
    goal = state.get('primary_goal') or {}
    if goal:
        out.append(f"Objetivo ativo: {goal.get('title')} ({goal.get('progress', 0)}%)")
    today = state.get('today') or {}
    out.append(
        f"Hoje: {today.get('tasks_open', 0)} tarefa(s) abertas, "
        f"{today.get('tasks_due', 0)} para hoje, {today.get('tasks_overdue', 0)} atrasada(s), "
        f"{today.get('active_schedules', 0)} agenda(s)/rotina(s) ativa(s)."
    )
    actions = list(state.get('next_actions') or [])[:max_actions]
    if actions:
        out.append('Próximas ações: ' + ' | '.join(f"[{a.get('id')}] {a.get('title')}" for a in actions))
    loops = list(state.get('open_loops') or [])[:4]
    if loops:
        out.append('Pendências abertas: ' + ' | '.join(str(x.get('title') or x.get('type')) for x in loops))
    results = list(state.get('recent_results') or [])[-2:]
    if results:
        out.append('Resultados recentes: ' + ' | '.join(str(x.get('text') or '')[:350] for x in results))
    return '\n'.join(out)


def note_turn(user_text: str, assistant_text: str) -> dict[str, Any]:
    # Mantém o foco conversacional recente sem transformar cada mensagem em uma nova sessão.
    context = f"Usuário: {str(user_text).strip()[:600]} | Hermes: {str(assistant_text).strip()[:900]}"
    return refresh(current_context=context, recent_result=assistant_text)
