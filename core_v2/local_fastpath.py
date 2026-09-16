from __future__ import annotations

from safe_time_router import handle as handle_time
from task_router import handle as handle_task
from temporal_parser import norm
from time_router import agenda


def handle(text: str) -> str | None:
    """Resolve operações locais óbvias sem depender do LLM.

    O LLM continua sendo o cérebro para linguagem ambígua/contextual, mas consultas
    simples de estado e comandos locais explícitos não podem falhar por timeout.
    """
    raw = str(text or '').strip()
    if not raw:
        return None
    t = norm(raw)

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

    # Quando o usuário pergunta pelas rotinas do dia, mostrar cada rotina uma vez,
    # não cada ocorrência de uma rotina intervalada (ex.: 39 avisos de água).
    if 'minhas rotinas' in t or 'quais rotinas' in t:
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
