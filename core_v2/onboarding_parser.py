#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import Any

from goal_manager import create_goal, infer_money_goal, list_goals
from opportunity_engine import add as add_opportunity, seed_from_profile
from personal_memory import add_skill, remember_fact, set_preference
from task_manager import create_task, list_tasks
from workflow_engine import build_goal_plan


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', text.strip()) if s.strip()]


def _clean_item(value: str) -> str:
    value = re.sub(r'^(?:e|tamb[eé]m|principalmente)\s+', '', value.strip(), flags=re.I)
    return value.strip(' .,:;-')


def _split_list(value: str) -> list[str]:
    value = re.sub(r'\s+e\s+', ',', value, flags=re.I)
    return [_clean_item(x) for x in value.split(',') if _clean_item(x)]


def is_onboarding(text: str) -> bool:
    low = text.casefold()
    markers = (
        'perfil principal', 'meu perfil', 'meu objetivo atual', 'meus principais interesses',
        'quero que você funcione', 'quero que voce funcione', 'salve este contexto',
        'a partir de agora', 'como primeiro experimento',
    )
    hits = sum(1 for m in markers if m in low)
    return len(text) >= 700 and hits >= 3


def _extract_skills(sentences: list[str]) -> list[str]:
    skills: list[str] = []
    patterns = (
        r'(?:meu foco principal [ée]|meu foco [ée])\s+(.+)',
        r'(?:trabalho com|sei trabalhar com|sei)\s+(.+)',
        r'(?:minhas habilidades (?:s[aã]o|incluem))\s+(.+)',
    )
    stop = re.compile(r'\b(?:mas|quando|porque|e quero|quero usar|consigo)\b', re.I)
    for sentence in sentences:
        for pattern in patterns:
            m = re.search(pattern, sentence, flags=re.I)
            if not m:
                continue
            chunk = stop.split(m.group(1), maxsplit=1)[0]
            for item in _split_list(chunk):
                if 1 <= len(item) <= 80 and item.casefold() not in [x.casefold() for x in skills]:
                    skills.append(item)
    return skills


def _find_or_create_money_goal(text: str) -> dict[str, Any] | None:
    inferred = infer_money_goal(text)
    if not inferred or not inferred.get('target_value'):
        return None
    target = float(inferred['target_value'])
    for goal in list_goals(include_done=False):
        try:
            if goal.get('category') == 'money' and float(goal.get('target_value') or 0) == target:
                return goal
        except Exception:
            pass
    return create_goal(**inferred)


def _extract_requested_tasks(text: str, goal_id: str | None) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    m = re.search(r'incluindo\s*:\s*(.+?)(?:\.(?:\s|$)|\n\n|$)', text, flags=re.I | re.S)
    if not m:
        return created
    raw = re.sub(r'\s+', ' ', m.group(1)).strip()
    items = _split_list(raw)
    existing = {str(t.get('title', '')).casefold() for t in list_tasks(goal_id=goal_id) if goal_id}
    for item in items[:20]:
        title = item[0].upper() + item[1:] if item else item
        if len(title) < 3 or title.casefold() in existing:
            continue
        created.append(create_task(title, goal_id=goal_id, priority='high', kind='onboarding'))
        existing.add(title.casefold())
    return created


def _capture_preferences(sentences: list[str]) -> int:
    count = 0
    for idx, sentence in enumerate(sentences):
        low = sentence.casefold()
        if any(k in low for k in ('eu prefiro', 'quero que você', 'quero que voce', 'sempre que', 'a partir de agora', 'quando eu pedir ajuda')):
            set_preference(f'onboarding_{idx+1}', sentence)
            count += 1
    return count


def _capture_facts(sentences: list[str], full_text: str) -> int:
    remember_fact('onboarding_context', full_text.strip())
    count = 1
    for key, markers in {
        'interesses': ('meus principais interesses', 'tenho interesse'),
        'estrategia_inicial': ('como primeiro experimento', 'primeiro experimento'),
        'perfil_profissional': ('eu sou ', 'sou desenvolvedor', 'sou desenvolvedora'),
    }.items():
        for sentence in sentences:
            if any(m in sentence.casefold() for m in markers):
                remember_fact(key, sentence)
                count += 1
                break
    return count


def process(text: str) -> str | None:
    if not is_onboarding(text):
        return None

    sentences = _sentences(text)
    skills = _extract_skills(sentences)
    for skill in skills:
        add_skill(skill)

    fact_count = _capture_facts(sentences, text)
    preference_count = _capture_preferences(sentences)

    goal = _find_or_create_money_goal(text)
    workflow_tasks: list[dict[str, Any]] = []
    custom_tasks: list[dict[str, Any]] = []
    if goal:
        workflow_tasks = build_goal_plan(goal['id'])
        custom_tasks = _extract_requested_tasks(text, goal['id'])

    seeded = seed_from_profile()

    experiment = next((s for s in sentences if 'primeiro experimento' in s.casefold()), '')
    if experiment:
        existing_titles = {x.get('title', '').casefold() for x in seeded}
        title = re.sub(r'^.*?primeiro experimento[,\s:;-]*', '', experiment, flags=re.I).strip()
        title = re.sub(r'^quero\s+(?:validar|testar)\s+', '', title, flags=re.I).strip(' .')
        if title and title.casefold() not in existing_titles:
            try:
                add_opportunity(title, source='onboarding', revenue_score=8, speed_score=8, fit_score=8, cost_score=2, risk_score=4,
                                notes='Estratégia inicial definida durante o onboarding.')
            except Exception:
                pass

    lines = [
        'Onboarding concluído e salvo localmente.',
        f'- Habilidades registradas: {len(skills)}',
        f'- Fatos/contexto salvos: {fact_count}',
        f'- Preferências/regras salvas: {preference_count}',
    ]
    if goal:
        lines.append(f"- Objetivo criado/identificado: [{goal['id']}] {goal['title']}")
        lines.append(f'- Tarefas do plano: {len(workflow_tasks)} | tarefas adicionais extraídas: {len(custom_tasks)}')
    else:
        lines.append('- Nenhum objetivo financeiro estruturado foi identificado.')
    lines.append(f'- Oportunidades novas sugeridas: {len(seeded)}')
    lines.append('Agora você pode perguntar: "o que fazemos hoje?", "meus objetivos", "minhas tarefas" ou "oportunidades para ganhar dinheiro".')
    return '\n'.join(lines)
