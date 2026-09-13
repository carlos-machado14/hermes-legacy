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
from proactive_engine import daily_brief, weekly_review, recommendation, continue_last, history as decision_history
from proactive_settings import enable as enable_proactive, disable as disable_proactive, summary as proactive_summary
from decision_log import record


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
        record('next_action', high[0].get('title',''), metadata={'task_id': high[0].get('id')})
    out.append(''); out.append('Minha prioridade é transformar isso em execução e receita, não só listar ideias.')
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

    if any(k in low for k in ('ative modo proativo', 'ativar modo proativo', 'liga modo proativo', 'ligue modo proativo', 'quero que me avise sozinho', 'seja proativo')):
        enable_proactive(); record('proactive_mode', 'Modo proativo ativado.'); return 'Modo proativo ativado. Vou acompanhar seus objetivos e te avisar nos momentos importantes.\n' + proactive_summary()
    if any(k in low for k in ('pause modo proativo', 'pausar modo proativo', 'desative modo proativo', 'desativar modo proativo', 'pare de me avisar sozinho')):
        disable_proactive(); record('proactive_mode', 'Modo proativo pausado.'); return 'Modo proativo pausado. Suas configurações e histórico foram preservados.'
    if any(k in low for k in ('status do modo proativo', 'como está o modo proativo', 'como esta o modo proativo', 'configuração proativa', 'configuracao proativa')):
        return proactive_summary()

    if low in {'skills', 'habilidades do hermes', 'o que voce sabe fazer', 'o que você sabe fazer'} or 'quais skills' in low: return skills_summary()
    if any(k in low for k in ('meus objetivos', 'listar objetivos', 'quais objetivos')): return goals_summary()
    if any(low.startswith(k) for k in ('crie objetivo ', 'criar objetivo ', 'novo objetivo ')):
        title = _after(t, ('crie objetivo', 'criar objetivo', 'novo objetivo')); g = create_goal(title); record('goal_created', g['title'], metadata={'goal_id': g['id']}); return f"Objetivo criado: [{g['id']}] {g['title']}"
    if any(k in low for k in ('quero ganhar ', 'meta de renda', 'meta de receita', 'quero faturar ')):
        inferred = infer_money_goal(t)
        if inferred:
            g = create_goal(**inferred); record('goal_created', g['title'], metadata={'goal_id': g['id']}); return f"Objetivo financeiro criado: [{g['id']}] {g['title']}\nUse: plano do objetivo {g['id']}"
    if low.startswith('concluir objetivo ') or low.startswith('finalizar objetivo '):
        ref = _after(t, ('concluir objetivo', 'finalizar objetivo'))
        try: g = complete_goal(ref); record('goal_completed', g['title'], metadata={'goal_id': g['id']}); return f"Objetivo concluído: {g['title']}"
        except KeyError: return 'Objetivo não encontrado.'
    if low.startswith('plano do objetivo ') or low.startswith('planeje objetivo '): return plan_summary(_after(t, ('plano do objetivo', 'planeje objetivo')))
    if any(k in low for k in ('minhas tarefas', 'listar tarefas', 'tarefas pendentes')): return tasks_summary()
    if any(low.startswith(k) for k in ('crie tarefa ', 'criar tarefa ', 'nova tarefa ')):
        task = create_task(_after(t, ('crie tarefa', 'criar tarefa', 'nova tarefa'))); record('task_created', task['title'], metadata={'task_id': task['id']}); return f"Tarefa criada: [{task['id']}] {task['title']}"
    if low.startswith('concluir tarefa ') or low.startswith('marque tarefa '):
        ref = re.sub(r'\s+como\s+conclu[ií]da.*$', '', _after(t, ('concluir tarefa', 'marque tarefa')), flags=re.I).strip()
        try: task = complete_task(ref); record('task_completed', task['title'], metadata={'task_id': task['id']}); return f"Tarefa concluída: {task['title']}"
        except KeyError: return 'Tarefa não encontrada.'

    money_phrases = (
        'oportunidade de ganhar dinheiro', 'oportunidades para ganhar dinheiro', 'oportunidades de renda',
        'oportunidade de renda', 'oportunidades de negocio', 'oportunidades de negócio', 'oportunidade de negocio',
        'oportunidade de negócio', 'como posso ganhar dinheiro', 'como ganhar dinheiro', 'formas de ganhar dinheiro',
        'com base minhas informações', 'com base nas minhas informações', 'com base no meu perfil', 'usando meu perfil',
    )
    if any(k in low for k in money_phrases): seed_from_profile(); return _money_advice()
    if low in {'oportunidades', 'minhas oportunidades'}: return opportunities_summary()

    if any(k in low for k in ('o que fazemos hoje', 'o que faço hoje', 'qual a prioridade', 'qual é a prioridade', 'o que devo fazer hoje', 'minha prioridade hoje')):
        return daily_brief()
    if any(k in low for k in ('como está minha semana', 'como esta minha semana', 'revisão da semana', 'revisao da semana', 'como estão meus objetivos', 'como estao meus objetivos')):
        return weekly_review()
    if any(k in low for k in ('o que você recomenda', 'o que voce recomenda', 'o que você faria no meu lugar', 'o que voce faria no meu lugar', 'o que devo mudar', 'qual objetivo está parado', 'qual objetivo esta parado')):
        return recommendation()
    if low in {'pode iniciar', 'pode começar', 'pode comecar', 'continue', 'continuar', 'vamos continuar', 'vamos seguir'}:
        return continue_last()
    if any(k in low for k in ('decisões recentes', 'decisoes recentes', 'histórico de decisões', 'historico de decisoes')):
        return decision_history()

    if low.startswith('lembre que eu sei ') or low.startswith('eu sei '):
        skill = _after(t, ('lembre que eu sei', 'eu sei')); add_skill(skill); return f'Habilidade registrada: {skill}'
    if low.startswith('lembre que '):
        fact = _after(t, ('lembre que',)); remember_fact('nota_' + str(abs(hash(fact)))[:8], fact); return 'Informação registrada no perfil pessoal.'
    if _asks_for_profile(low): return profile_summary()
    if low.startswith('pesquise ') or low.startswith('pesquisar '): return format_results(_after(t, ('pesquise', 'pesquisar')))
    return None
