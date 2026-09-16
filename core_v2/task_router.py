from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from agent_state import get as get_agent_state, refresh as refresh_agent_state
from task_manager import complete_task, list_tasks, update_task
from temporal_parser import norm, parse, tz
from time_store import DEFAULT_TZ

_STOP = {
    'a','o','as','os','de','da','do','das','dos','para','pra','por','que','eu','vc','voce','você','me','minha','meu',
    'tarefa','task','acao','ação','atividade','essa','esse','isso','aquela','aquele','tal','como','marcar','marca','marque',
    'finalizada','finalizado','concluida','concluída','concluido','concluído','feito','feita','terminei','concluir','conclui',
    'reagendar','reagenda','reagende','reagendei','mudar','mude','movi','altere','alterar','cancelar','cancela','cancele','remover','remova',
}


def _tokens(text: str) -> set[str]:
    return {x for x in re.findall(r'[a-z0-9à-ÿ]+', norm(text)) if len(x) >= 2 and x not in _STOP}


def _score(tokens: set[str], task: dict[str, Any]) -> int:
    target = _tokens(str(task.get('title') or ''))
    if not tokens or not target:
        return 0
    overlap = len(tokens & target)
    score = overlap * 5
    if tokens <= target:
        score += 8
    if task.get('status') == 'todo':
        score += 1
    return score


def _resolve(text: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    raw = str(text or '').strip()
    direct = re.search(r'\b([0-9a-f]{6,16})\b', raw, re.I)
    if direct:
        key = direct.group(1).casefold()
        for task in list_tasks():
            if str(task.get('id') or '').casefold().startswith(key):
                return task, []

    tokens = _tokens(raw)
    ranked: list[tuple[int, dict[str, Any]]] = []
    for task in list_tasks():
        score = _score(tokens, task)
        if score > 0:
            ranked.append((score, task))
    ranked.sort(key=lambda x: (x[0], int(x[1].get('updated_at') or 0)), reverse=True)
    if not ranked:
        return None, []
    best = ranked[0][0]
    matches = [task for score, task in ranked if score == best]
    if len(matches) == 1:
        return matches[0], []
    return None, matches[:5]


def _ambiguous(rows: list[dict[str, Any]]) -> str:
    lines = ['Encontrei mais de uma tarefa parecida:']
    for i, task in enumerate(rows, 1):
        lines.append(f"{i}. {task.get('title')} [ID {task.get('id')}]")
    lines.append('Me diga qual delas pelo assunto ou ID.')
    return '\n'.join(lines)


def _due_from_text(text: str) -> str | None:
    parsed = parse(text)
    if not parsed or not parsed.get('next_run_at'):
        return None
    try:
        zone = tz(parsed.get('timezone') or DEFAULT_TZ)
        return datetime.fromtimestamp(int(parsed['next_run_at']), zone).isoformat()
    except Exception:
        return None


def _is_list_query(t: str) -> bool:
    direct = (
        'minhas tarefas', 'tarefas de hoje', 'tasks de hoje', 'o que tenho para fazer',
        'o que preciso fazer', 'quais tarefas', 'quais tasks', 'que tarefas', 'que tasks',
        'tarefas eu tenho', 'tasks eu tenho', 'tenho tarefas', 'tenho tasks',
    )
    if any(x in t for x in direct):
        return True
    has_task_word = any(x in t for x in ('tarefa', 'tarefas', 'task', 'tasks'))
    has_query_word = any(x in t for x in ('quais', 'qual', 'tenho', 'listar', 'lista', 'mostra', 'mostrar', 'pendentes', 'hoje'))
    return has_task_word and has_query_word and '?' in t


def _agent_followup(base: str, result: str) -> str:
    try:
        refresh_agent_state(recent_result=result)
        state = get_agent_state()
        actions = list(state.get('next_actions') or [])
        if actions:
            return base + f"\n➡️ Próximo passo: {actions[0].get('title')}"
    except Exception:
        pass
    return base


def handle(text: str) -> str | None:
    raw = str(text or '').strip()
    if not raw:
        return None
    t = norm(raw)

    is_complete = any(x in t for x in ('finalizei','finalizada','finalizado','conclui','concluida','concluido','terminei','ja fiz','já fiz','feito','feita'))
    is_reschedule = any(x in t for x in ('reagende','reagenda','reagendar','reagendei','mude para','mudar para','movi para','altere para','alterar para'))
    is_cancel = any(x in t for x in ('cancele','cancela','cancelar','remova','remover','apague','apagar'))
    is_list = _is_list_query(t)

    if is_list:
        rows = [x for x in list_tasks(status='todo')]
        if not rows:
            return 'Você não tem tarefas pendentes registradas.'
        rows.sort(key=lambda x: (str(x.get('due') or '9999'), {'high':0,'medium':1,'low':2}.get(x.get('priority','medium'),1)))
        lines = ['✅ Tarefas pendentes:']
        for task in rows[:20]:
            due = f" — {task.get('due')}" if task.get('due') else ''
            lines.append(f"- {task.get('title')}{due} [ID {task.get('id')}] ")
        return '\n'.join(lines)

    if not (is_complete or is_reschedule or is_cancel):
        return None

    task, ambiguous = _resolve(raw)
    if ambiguous:
        return _ambiguous(ambiguous)
    if not task:
        return 'Não encontrei com segurança qual tarefa você quis dizer. Me fale o assunto dela.'

    ref = str(task.get('id'))
    if is_complete:
        done = complete_task(ref)
        result = f"Concluída: {done.get('title')}"
        return _agent_followup(f"✅ Marquei como concluída: {done.get('title')}", result)
    if is_cancel:
        cancelled = update_task(ref, status='cancelled', cancelled_at=int(datetime.now().timestamp()))
        result = f"Cancelada: {cancelled.get('title')}"
        return _agent_followup(f"🗑️ Cancelei a tarefa: {cancelled.get('title')}", result)
    if is_reschedule:
        due = _due_from_text(raw)
        if not due:
            return f"Para quando você quer reagendar '{task.get('title')}'?"
        updated = update_task(ref, due=due, status='todo')
        try:
            pretty = datetime.fromisoformat(due).strftime('%d/%m/%Y %H:%M')
        except Exception:
            pretty = due
        result = f"Reagendada: {updated.get('title')} para {pretty}"
        return _agent_followup(f"📅 Reagendei: {updated.get('title')} para {pretty}.", result)
    return None
