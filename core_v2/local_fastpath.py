from __future__ import annotations

from safe_time_router import handle as handle_time
from subconscious_router import handle as handle_subconscious
from task_router import handle as handle_task
from temporal_parser import norm
from time_router import agenda


def handle(text: str) -> str | None:
    """Resolve estado local antes de recorrer ao LLM.

    O subconscious router é uma camada de recuperação read-only: ele interpreta
    consultas naturais sobre agenda/rotinas diretamente do estado local, inclusive
    horários e períodos, sem depender de uma frase exata nem de disponibilidade do modelo.
    """
    raw = str(text or '').strip()
    if not raw:
        return None
    t = norm(raw)

    # Primeiro tenta compreender consultas locais por estrutura semântica ampla.
    subconscious = handle_subconscious(raw)
    if subconscious is not None:
        return subconscious

    task_hints = (
        'tarefa', 'tarefas', 'task', 'tasks', 'o que tenho para fazer',
        'o que preciso fazer', 'finalizei ', 'conclui ', 'terminei ',
        'reagenda ', 'reagende ', 'reagendei ', 'cancela a task', 'cancele a task',
        'cancela a tarefa', 'cancele a tarefa',
    )
    if any(h in t for h in task_hints):
        reply = handle_task(raw)
        if reply is not None:
            return reply

    # Rotinas sem filtro de horário são agrupadas uma vez por rotina.
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
