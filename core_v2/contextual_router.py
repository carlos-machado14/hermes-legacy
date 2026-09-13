#!/usr/bin/env python3
from __future__ import annotations

from context_builder import primary_goal
from goal_manager import update_goal
from workflow_engine import build_goal_plan
from decision_log import record


def _looks_like_goal_reference(low: str) -> bool:
    return any(k in low for k in (
        'esse objetivo', 'este objetivo', 'meu objetivo', 'objetivo financeiro',
        'nesse objetivo', 'neste objetivo', 'para o objetivo', 'no objetivo',
    ))


def _looks_like_attach_intent(low: str) -> bool:
    return any(k in low for k in (
        'coloca', 'coloque', 'inserir', 'insere', 'inclui', 'incluir', 'adicione', 'adicionar',
        'pensei para', 'pensei em usar', 'quero usar', 'vamos usar', 'faz parte', 'fazer parte',
        'aquela rotina', 'essa rotina', 'essa ideia', 'aquela ideia',
    ))


def handle(text: str) -> str | None:
    t = text.strip()
    low = t.lower()
    goal = primary_goal()
    if not goal:
        return None

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
