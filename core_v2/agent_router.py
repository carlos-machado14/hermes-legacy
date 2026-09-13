#!/usr/bin/env python3
from __future__ import annotations

import re

from goal_manager import create_goal, infer_money_goal, summary as goals_summary, complete_goal
from task_manager import create_task, summary as tasks_summary, complete_task
from workflow_engine import plan_summary
from opportunity_engine import seed_from_profile, summary as opportunities_summary
from personal_memory import add_skill, remember_fact, summary as profile_summary
from skill_registry import describe as skills_summary
from research_engine import format_results
from onboarding_parser import process as process_onboarding


def _after(text: str, markers: tuple[str, ...]) -> str:
    low = text.lower()
    for marker in markers:
        i = low.find(marker)
        if i >= 0:
            return text[i + len(marker):].strip(' :,-')
    return ''


def handle(text: str) -> str | None:
    onboarding = process_onboarding(text)
    if onboarding is not None:
        return onboarding

    t = text.strip(); low = t.lower()

    if low in {'skills', 'habilidades do hermes', 'o que voce sabe fazer', 'o que você sabe fazer'} or 'quais skills' in low:
        return skills_summary()
    if any(k in low for k in ('meus objetivos', 'listar objetivos', 'quais objetivos')):
        return goals_summary()
    if any(low.startswith(k) for k in ('crie objetivo ', 'criar objetivo ', 'novo objetivo ')):
        title = _after(t, ('crie objetivo', 'criar objetivo', 'novo objetivo')); g = create_goal(title)
        return f"Objetivo criado: [{g['id']}] {g['title']}"
    if any(k in low for k in ('quero ganhar ', 'meta de renda', 'meta de receita', 'quero faturar ')):
        inferred = infer_money_goal(t)
        if inferred:
            g = create_goal(**inferred)
            return f"Objetivo financeiro criado: [{g['id']}] {g['title']}\nUse: plano do objetivo {g['id']}"
    if low.startswith('concluir objetivo ') or low.startswith('finalizar objetivo '):
        ref = _after(t, ('concluir objetivo', 'finalizar objetivo'))
        try: g = complete_goal(ref); return f"Objetivo concluído: {g['title']}"
        except KeyError: return 'Objetivo não encontrado.'
    if low.startswith('plano do objetivo ') or low.startswith('planeje objetivo '):
        return plan_summary(_after(t, ('plano do objetivo', 'planeje objetivo')))
    if any(k in low for k in ('minhas tarefas', 'listar tarefas', 'tarefas pendentes')):
        return tasks_summary()
    if any(low.startswith(k) for k in ('crie tarefa ', 'criar tarefa ', 'nova tarefa ')):
        task = create_task(_after(t, ('crie tarefa', 'criar tarefa', 'nova tarefa')))
        return f"Tarefa criada: [{task['id']}] {task['title']}"
    if low.startswith('concluir tarefa ') or low.startswith('marque tarefa '):
        ref = re.sub(r'\s+como\s+conclu[ií]da.*$', '', _after(t, ('concluir tarefa', 'marque tarefa')), flags=re.I).strip()
        try: task = complete_task(ref); return f"Tarefa concluída: {task['title']}"
        except KeyError: return 'Tarefa não encontrada.'
    if any(k in low for k in ('oportunidades para ganhar dinheiro', 'oportunidades de renda', 'oportunidades de negocio', 'oportunidades de negócio')):
        seed_from_profile(); return opportunities_summary()
    if low in {'oportunidades', 'minhas oportunidades'}:
        return opportunities_summary()
    if low.startswith('lembre que eu sei ') or low.startswith('eu sei '):
        skill = _after(t, ('lembre que eu sei', 'eu sei')); add_skill(skill); return f'Habilidade registrada: {skill}'
    if low.startswith('lembre que '):
        fact = _after(t, ('lembre que',)); remember_fact('nota_' + str(abs(hash(fact)))[:8], fact)
        return 'Informação registrada no perfil pessoal.'
    if low in {'meu perfil', 'perfil pessoal', 'o que voce sabe sobre mim', 'o que você sabe sobre mim'}:
        return profile_summary()
    if low.startswith('pesquise ') or low.startswith('pesquisar '):
        return format_results(_after(t, ('pesquise', 'pesquisar')))
    return None
