#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from goal_manager import get_goal
from task_manager import create_task, list_tasks

MONEY_STEPS = [
    ('Definir oferta principal e ticket alvo', 'high'),
    ('Escolher nicho e perfil de cliente ideal', 'high'),
    ('Montar proposta curta com problema, solução, prazo e preço', 'high'),
    ('Criar lista inicial de 30 potenciais clientes', 'high'),
    ('Fazer primeira rodada de prospecção', 'high'),
    ('Registrar respostas e objeções', 'medium'),
    ('Fazer follow-up dos contatos sem resposta', 'high'),
    ('Revisar conversão e ajustar oferta', 'medium'),
]

GENERAL_STEPS = [
    ('Definir resultado esperado e critério de sucesso', 'high'),
    ('Quebrar o objetivo em três próximos passos executáveis', 'high'),
    ('Executar o primeiro passo', 'high'),
    ('Revisar progresso e ajustar o plano', 'medium'),
]


def build_goal_plan(goal_ref: str) -> list[dict[str, Any]]:
    goal = get_goal(goal_ref)
    if not goal: raise KeyError(goal_ref)
    existing = list_tasks(goal_id=goal['id'])
    if existing: return existing
    steps = MONEY_STEPS if goal.get('category') == 'money' else GENERAL_STEPS
    return [create_task(title, goal_id=goal['id'], priority=priority, kind='workflow_step') for title, priority in steps]


def plan_summary(goal_ref: str) -> str:
    goal = get_goal(goal_ref)
    if not goal: return 'Objetivo não encontrado.'
    tasks = build_goal_plan(goal_ref)
    out = [f"Plano para: {goal['title']}"]
    for i,t in enumerate(tasks, 1): out.append(f"{i}. [{t['id']}] {t['title']} | {t.get('status','todo')}")
    return '\n'.join(out)
