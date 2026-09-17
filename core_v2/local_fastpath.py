from __future__ import annotations

from day_overview import render as render_day_overview
from local_action_intent import handle as handle_local_action
from safe_time_router import handle as handle_time
from subconscious_router import handle as handle_subconscious
from task_router import handle as handle_task
from temporal_parser import norm
from time_router import agenda


def handle(text: str) -> str | None:
    """Fastpath local para estado e ações internas simples.

    Ações locais seguras (agenda/lembretes/rotinas) podem ser resolvidas sem LLM
    quando a intenção é inequívoca. Consultas também são atendidas localmente.
    Linguagem ambígua continua indo para o cérebro semântico.
    """
    raw = str(text or '').strip()
    if not raw:
        return None
    t = norm(raw)

    # Primeiro: mutações internas simples e inequívocas. Isso evita que cancelar
    # todos os lembretes dependa da disponibilidade do modelo.
    local_action = handle_local_action(raw)
    if local_action is not None:
        return local_action

    overview = render_day_overview(raw)
    if overview is not None:
        return overview

    subconscious = handle_subconscious(raw)
    if subconscious is not None:
        return subconscious

    task_query_hints = (
        'tarefa', 'tarefas', 'task', 'tasks', 'o que tenho para fazer',
        'o que preciso fazer', 'o que falta fazer', 'pendencias', 'pendências',
    )
    mutation_hints = (
        'finaliz', 'conclu', 'termin', 'reagend', 'cancel', 'exclu', 'remov',
        'apag', 'paus', 'retom', 'alter', 'mud', 'crie', 'criar', 'adicione',
    )
    if any(h in t for h in task_query_hints) and not any(h in t for h in mutation_hints):
        reply = handle_task(raw)
        if reply is not None:
            return reply

    if ('minhas rotinas' in t or 'quais rotinas' in t) and not any(ch.isdigit() for ch in t):
        if 'amanha' in t:
            return agenda('tomorrow')
        return agenda('today')

    time_query_hints = (
        'agenda de hoje', 'agenda hoje', 'minha agenda hoje', 'o que tenho hoje',
        'agenda de amanha', 'agenda amanhã', 'minha agenda amanha', 'minha agenda amanhã',
        'meus lembretes', 'quais lembretes',
    )
    if any(h in t for h in time_query_hints):
        reply = handle_time(raw)
        if reply is not None:
            return reply

    return None
