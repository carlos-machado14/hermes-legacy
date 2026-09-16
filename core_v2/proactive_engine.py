#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime

from agent_state import get as get_agent_state, refresh as refresh_agent_state
from context_builder import snapshot, primary_goal, ranked_tasks
from decision_log import record, summary as decisions_summary
from time_router import agenda


def _task_bucket(tasks: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    today = datetime.now().date()
    due_today: list[dict] = []
    overdue: list[dict] = []
    other: list[dict] = []
    for task in tasks:
        due = str(task.get('due') or '').strip()
        if not due:
            other.append(task)
            continue
        try:
            d = datetime.fromisoformat(due).date()
        except Exception:
            other.append(task)
            continue
        if d < today:
            overdue.append(task)
        elif d == today:
            due_today.append(task)
        else:
            other.append(task)
    return due_today, overdue, other


def _next_step(tasks: list[dict]) -> dict | None:
    return tasks[0] if tasks else None


def daily_brief() -> str:
    refresh_agent_state()
    state = get_agent_state()
    ctx = snapshot()
    goal = primary_goal(ctx)
    tasks = ranked_tasks(ctx)
    due_today, overdue, other = _task_bucket(tasks)
    focus = due_today + overdue + other

    out: list[str] = []
    try:
        out.append(agenda('today'))
    except Exception:
        out.append('📅 Não consegui carregar sua agenda agora.')

    out.extend(['', '📌 O que precisa da sua atenção'])
    if overdue:
        for task in overdue[:4]:
            out.append(f"- Atrasada: {task.get('title')} [ID {task.get('id')}]")
    if due_today:
        for task in due_today[:5]:
            out.append(f"- Hoje: {task.get('title')} [ID {task.get('id')}]")
    if not overdue and not due_today:
        out.append('- Nenhuma tarefa com prazo hoje ou atrasada.')

    next_task = _next_step(focus)
    if next_task:
        out.extend(['', '🎯 Próximo passo útil', f"- {next_task.get('title')}"])
        record('next_action', next_task.get('title',''), metadata={'task_id':next_task.get('id')})

    open_loops = list(state.get('open_loops') or [])
    non_task_loops = [x for x in open_loops if x.get('type') != 'task']
    if non_task_loops:
        out.extend(['', '🧠 Pendências que estou acompanhando'])
        for item in non_task_loops[:4]:
            out.append(f"- {item.get('title') or item.get('type')}")

    if goal:
        out.extend(['', f"🏁 Objetivo em andamento: {goal.get('title')} — {goal.get('progress',0)}%"])

    if not focus and not non_task_loops:
        out.extend(['', 'Seu dia está sem pendências operacionais relevantes no momento.'])
    return '\n'.join(out)


def weekly_review() -> str:
    refresh_agent_state()
    state = get_agent_state()
    ctx = snapshot()
    goals = ctx.get('goals') or []
    tasks = ranked_tasks(ctx)
    due_today, overdue, other = _task_bucket(tasks)
    out=['Revisão atual:']
    if goals:
        for g in goals[:5]:
            out.append(f"- Objetivo: {g.get('title')} | progresso={g.get('progress',0)}% | prazo={g.get('deadline') or 'não definido'}")
    else:
        out.append('- Nenhum objetivo ativo.')
    out.append(f'- Tarefas abertas: {len(tasks)}')
    out.append(f'- Atrasadas: {len(overdue)}')
    out.append(f'- Para hoje: {len(due_today)}')
    pending = list(state.get('pending_decisions') or [])
    if pending:
        out.append(f'- Decisões pendentes: {len(pending)}')
    if tasks:
        out.append(f"- Próximo passo recomendado: {tasks[0].get('title')}")
    try:
        out.extend(['', agenda('week')])
    except Exception:
        pass
    return '\n'.join(out)


def recommendation() -> str:
    refresh_agent_state()
    state = get_agent_state()
    ctx = snapshot()
    goal = primary_goal(ctx)
    tasks = ranked_tasks(ctx)
    overdue = [x for x in list(state.get('open_loops') or []) if x.get('status') == 'overdue']
    out=['Minha leitura do momento:']
    if overdue:
        out.append(f"- Existem {len(overdue)} pendência(s) atrasada(s) que merecem atenção primeiro.")
    if goal:
        out.append(f"- Objetivo ativo: {goal.get('title')}.")
    if tasks:
        out.append(f"- Próxima ação concreta: {tasks[0].get('title')}.")
    else:
        out.append('- Não há tarefa concreta aberta; vale definir o próximo passo do objetivo principal.')
    return '\n'.join(out)


def continue_last() -> str:
    state = get_agent_state(refresh_state=True)
    actions = list(state.get('next_actions') or [])
    if actions:
        return f"Vamos continuar por: {actions[0].get('title')}."
    from decision_log import recent
    rows=recent(20,kind='next_action')
    if not rows:
        return 'Ainda não há uma próxima ação registrada.'
    item=rows[-1]
    return f"Vamos continuar pela próxima ação definida: {item.get('summary')}."


def history() -> str:
    return decisions_summary(10)
