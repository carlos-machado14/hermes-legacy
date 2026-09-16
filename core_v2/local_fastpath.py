from __future__ import annotations

from conversation_action_router import handle as handle_conversation_action
from safe_time_router import handle as handle_time
from subconscious_router import handle as handle_subconscious
from task_router import handle as handle_task
from temporal_parser import norm
from time_router import agenda


def handle(text: str) -> str | None:
    """Resolve estado e ações locais óbvias antes de recorrer ao LLM.

    Consultas e mutações explícitas sobre agenda devem continuar funcionando mesmo
    quando o modelo estiver lento ou indisponível. O LLM fica para linguagem ambígua
    e raciocínio, não para operações locais que já possuem estado estruturado.
    """
    raw = str(text or '').strip()
    if not raw:
        return None
    t = norm(raw)

    # Ações locais explícitas (inclusive follow-ups como "exclui todas elas")
    # precisam ocorrer antes do Conversation Brain para não depender do LLM.
    action_reply = handle_conversation_action(raw)
    if action_reply is not None:
        return action_reply

    # Recuperação read-only ampla para agenda/rotinas/horários.
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
