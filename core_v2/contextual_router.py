#!/usr/bin/env python3
from __future__ import annotations

from context_builder import primary_goal
from goal_manager import update_goal
from workflow_engine import build_goal_plan
from decision_log import record
from site_sales_workflow import configure_for_primary_goal


def _looks_like_goal_reference(low: str) -> bool:
    return any(k in low for k in (
        'esse objetivo', 'este objetivo', 'meu objetivo', 'objetivo financeiro',
        'nesse objetivo', 'neste objetivo', 'para o objetivo', 'no objetivo',
    ))


def _looks_like_attach_intent(low: str) -> bool:
    return any(k in low for k in (
        'coloca', 'coloque', 'inserir', 'insere', 'inclui', 'incluir', 'adicione', 'adicionar',
        'pensei para', 'pensei em usar', 'quero usar', 'vamos usar', 'faz parte', 'fazer parte',
        'aquela rotina', 'essa rotina', 'essa ideia', 'aquela ideia', 'alimentar meu objetivo',
    ))


def _looks_like_daily_site_strategy(low: str) -> bool:
    daily = any(k in low for k in ('todo dia', 'todos os dias', 'diariamente', 'por dia'))
    site = 'site' in low
    company = any(k in low for k in ('empresa', 'cliente', 'negócio', 'negocio'))
    condition = any(k in low for k in ('sem site', 'não possua site', 'nao possua site', 'site antigo', 'site muito antigo', 'desatualizado'))
    create = any(k in low for k in ('criar', 'gere', 'gerar', 'montar', 'fazer', 'melhorar'))
    return daily and site and company and condition and create


def handle(text: str) -> str | None:
    t = text.strip()
    low = t.lower()
    goal = primary_goal()
    if not goal:
        return None

    if _looks_like_daily_site_strategy(low):
        return configure_for_primary_goal()

    if _looks_like_goal_reference(low) and _looks_like_attach_intent(low):
        old = str(goal.get('notes') or '').strip()
        note = t
        if note.casefold() not in old.casefold():
            merged = (old + '\n' + note).strip() if old else note
            goal = update_goal(goal['id'], notes=merged)
        tasks = build_goal_plan(goal['id'])
        record('goal_context_updated', note, metadata={'goal_id': goal['id']})
        return (
            f"Entendi. Vinculei essa ideia ao objetivo: {goal['title']}.\n"
            f"Vou considerar isso como parte da estratégia daqui para frente. "
            f"O objetivo agora tem {len(tasks)} tarefa(s) de execução associada(s)."
        )

    if low in {'isso', 'é isso', 'isso mesmo', 'exatamente', 'perfeito'}:
        return 'Certo. Mantive o contexto atual e vou continuar a partir dele.'

    return None
