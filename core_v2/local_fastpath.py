from __future__ import annotations

from day_overview import render as render_day_overview
from safe_time_router import handle as handle_time
from subconscious_router import handle as handle_subconscious
from task_router import handle as handle_task
from temporal_parser import norm
from time_router import agenda


def handle(text: str) -> str | None:
    """Fastpath somente para leitura de estado local.

    Regras determinísticas aqui não decidem mais mutações. Criar, cancelar,
    reagendar, pausar, retomar ou concluir passa primeiro pelo cérebro semântico.
    Esta camada só responde consultas locais seguras sem depender da disponibilidade
    do modelo.
    """
    raw = str(text or '').strip()
    if not raw:
        return None
    t = norm(raw)

    # Consulta genérica do dia: detectada por estrutura (pergunta + referência temporal
    # sem entidade específica), não por uma frase exata. Exemplos de redações livres
    # como "oq temos pra hoje?" e "e amanhã?" não precisam passar pelo LLM.
    overview = render_day_overview(raw)
    if overview is not None:
        return overview

    # Recuperação read-only ampla para agenda/rotinas/horários específicos.
    subconscious = handle_subconscious(raw)
    if subconscious is not None:
        return subconscious

    # Consultas simples de tarefas continuam locais por desempenho. Nenhuma mutação
    # de tarefa é executada por esta camada.
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

    # Compatibilidade de leitura agrupada; ações nunca entram aqui.
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
