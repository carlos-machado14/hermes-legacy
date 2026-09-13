#!/usr/bin/env python3
from __future__ import annotations

import re

from goal_manager import create_goal, infer_money_goal, summary as goals_summary, complete_goal, list_goals
from task_manager import create_task, summary as tasks_summary, complete_task, list_tasks
from workflow_engine import plan_summary
from opportunity_engine import seed_from_profile, summary as opportunities_summary, list_items as list_opportunities
from personal_memory import add_skill, remember_fact, summary as profile_summary, profile
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


def _money_advice() -> str:
    p = profile(); skills = p.get('skills') or []
    goals = [g for g in list_goals(include_done=False) if g.get('category') == 'money']
    if not list_opportunities(): seed_from_profile()
    opportunities = list_opportunities()[:5]; tasks = list_tasks(status='todo')
    out = ['Com base no seu perfil salvo:']
    if skills: out.append('- Habilidades: ' + ', '.join(skills[:12]))
    if goals:
        g = goals[-1]
        target = f"R$ {float(g.get('target_value') or 0):,.0f}".replace(',', '.') if g.get('target_value') else g.get('title')
        out.append(f"- Objetivo financeiro ativo: {target} | prazo={g.get('deadline') or 'não definido'}")
    if opportunities:
        out.append(''); out.append('Melhores oportunidades agora:')
        for i, item in enumerate(opportunities[:5], 1): out.append(f"{i}. {item.get('title')} | score={item.get('score', 0)}/100")
    if tasks:
        high = [t for t in tasks if t.get('priority') == 'high'] or tasks
        out.append(''); out.append('Próximas ações:')
        for i, task in enumerate(high[:5], 1): out.append(f"{i}. {task.get('title')}")
    out.append(''); out.append('Minha prioridade é transformar isso em execução e receita, não só listar ideias.')
    return '\n'.join(out)


def _today_plan() -> str:
    goals = list_goals(include_done=False); tasks = list_tasks(status='todo'); opportunities = list_opportunities()
    if not opportunities: seed_from_profile(); opportunities = list_opportunities()
    out = ['Plano de hoje:']
    if goals: out.append(f"Objetivo principal: {goals[-1].get('title')}")
    high = [t for t in tasks if t.get('priority') == 'high'] or tasks
    if high:
        out.append('Prioridades:')
        for i, task in enumerate(high[:5], 1): out.append(f"{i}. {task.get('title')}")
    if opportunities: out.append(f"Melhor oportunidade atual: {opportunities[0].get('title')} (score {opportunities[0].get('score',0)}/100)")
    if not tasks: out.append('Ainda não há tarefas pendentes; peça "plano do objetivo <ID>" para gerar o plano.')
    return '\n'.join(out)


def _asks_for_profile(low: str) -> bool:
    direct = (
        'meu perfil', 'perfil pessoal', 'dados do meu perfil', 'dados do perfil', 'meus dados',
        'minhas informações', 'minhas informacoes', 'informações sobre mim', 'informacoes sobre mim',
        'o que voce sabe sobre mim', 'o que você sabe sobre mim', 'quem eu sou', 'o que sabe de mim',
        'o que você lembra de mim', 'o que voce lembra de mim',
    )
    if any(k in low for k in direct): return True
    return 'perfil' in low and any(k in low for k in ('quais', 'dados', 'informa', 'mostre', 'liste', 'salvo', 'tenho'))


def handle(text: str) -> str | None:
    onboarding = process_onboarding(text)
    if onboarding is not None: return onboarding
    t = text.strip(); low = t.lower()

    if low in {'skills', 'habilidades do hermes', 'o que voce sabe fazer', 'o que você sabe fazer'} or 'quais skills' in low: return skills_summary()
    if any(k in low for k in ('meus objetivos', 'listar objetivos', 'quais objetivos')): return goals_summary()
    if any(low.startswith(k) for k in ('crie objetivo ', 'criar objetivo ', 'novo objetivo ')):
        title = _after(t, ('crie objetivo', 'criar objetivo', 'novo objetivo')); g = create_goal(title); return f"Objetivo criado: [{g['id']}] {g['title']}"
    if any(k in low for k in ('quero ganhar ', 'meta de renda', 'meta de receita', 'quero faturar ')):
        inferred = infer_money_goal(t)
        if inferred:
            g = create_goal(**inferred); return f"Objetivo financeiro criado: [{g['id']}] {g['title']}\nUse: plano do objetivo {g['id']}"
    if low.startswith('concluir objetivo ') or low.startswith('finalizar objetivo '):
        ref = _after(t, ('concluir objetivo', 'finalizar objetivo'))
        try: g = complete_goal(ref); return f"Objetivo concluído: {g['title']}"
        except KeyError: return 'Objetivo não encontrado.'
    if low.startswith('plano do objetivo ') or low.startswith('planeje objetivo '): return plan_summary(_after(t, ('plano do objetivo', 'planeje objetivo')))
    if any(k in low for k in ('minhas tarefas', 'listar tarefas', 'tarefas pendentes')): return tasks_summary()
    if any(low.startswith(k) for k in ('crie tarefa ', 'criar tarefa ', 'nova tarefa ')):
        task = create_task(_after(t, ('crie tarefa', 'criar tarefa', 'nova tarefa'))); return f"Tarefa criada: [{task['id']}] {task['title']}"
    if low.startswith('concluir tarefa ') or low.startswith('marque tarefa '):
        ref = re.sub(r'\s+como\s+conclu[ií]da.*$', '', _after(t, ('concluir tarefa', 'marque tarefa')), flags=re.I).strip()
        try: task = complete_task(ref); return f"Tarefa concluída: {task['title']}"
        except KeyError: return 'Tarefa não encontrada.'

    money_phrases = (
        'oportunidade de ganhar dinheiro', 'oportunidades para ganhar dinheiro', 'oportunidades de renda',
        'oportunidade de renda', 'oportunidades de negocio', 'oportunidades de negócio', 'oportunidade de negocio',
        'oportunidade de negócio', 'como posso ganhar dinheiro', 'como ganhar dinheiro', 'formas de ganhar dinheiro',
        'com base minhas informações', 'com base nas minhas informações', 'com base no meu perfil', 'usando meu perfil',
    )
    if any(k in low for k in money_phrases): seed_from_profile(); return _money_advice()
    if low in {'oportunidades', 'minhas oportunidades'}: return opportunities_summary()
    if any(k in low for k in ('o que fazemos hoje', 'o que faço hoje', 'qual a prioridade', 'qual é a prioridade', 'o que devo fazer hoje')): return _today_plan()

    if low.startswith('lembre que eu sei ') or low.startswith('eu sei '):
        skill = _after(t, ('lembre que eu sei', 'eu sei')); add_skill(skill); return f'Habilidade registrada: {skill}'
    if low.startswith('lembre que '):
        fact = _after(t, ('lembre que',)); remember_fact('nota_' + str(abs(hash(fact)))[:8], fact); return 'Informação registrada no perfil pessoal.'
    if _asks_for_profile(low): return profile_summary()
    if low.startswith('pesquise ') or low.startswith('pesquisar '): return format_results(_after(t, ('pesquise', 'pesquisar')))
    return None
