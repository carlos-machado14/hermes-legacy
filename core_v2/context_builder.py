#!/usr/bin/env python3
from __future__ import annotations

import time
from typing import Any

from personal_memory import profile
from goal_manager import list_goals
from task_manager import list_tasks
from opportunity_engine import list_items as list_opportunities, seed_from_profile
from project_registry import public_summary as project_summary


def snapshot() -> dict[str, Any]:
    opportunities = list_opportunities()
    if not opportunities:
        seed_from_profile()
        opportunities = list_opportunities()
    return {
        'ts': int(time.time()),
        'profile': profile(),
        'goals': list_goals(include_done=False),
        'tasks': list_tasks(status='todo'),
        'opportunities': opportunities,
        'projects': project_summary(),
    }


def primary_goal(ctx: dict[str, Any] | None = None) -> dict[str, Any] | None:
    ctx = ctx or snapshot()
    goals = list(ctx.get('goals') or [])
    if not goals:
        return None
    money = [g for g in goals if g.get('category') == 'money']
    return (money or goals)[-1]


def ranked_tasks(ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    ctx = ctx or snapshot()
    rank = {'high': 0, 'medium': 1, 'low': 2}
    return sorted(list(ctx.get('tasks') or []), key=lambda x: (rank.get(x.get('priority', 'medium'), 1), x.get('created_at', 0)))


def best_opportunity(ctx: dict[str, Any] | None = None) -> dict[str, Any] | None:
    ctx = ctx or snapshot()
    rows = list(ctx.get('opportunities') or [])
    if not rows:
        return None
    return sorted(rows, key=lambda x: float(x.get('score') or 0), reverse=True)[0]


def compact(ctx: dict[str, Any] | None = None, *, max_items: int = 5) -> str:
    ctx = ctx or snapshot()
    p = ctx.get('profile') or {}
    out = ['CONTEXTO PESSOAL ATUAL DO USUARIO']
    skills = p.get('skills') or []
    if skills:
        out.append('Habilidades: ' + ', '.join(skills[:12]))
    facts = p.get('facts') or {}
    if facts:
        out.append('Fatos: ' + '; '.join(f'{k}={v}' for k, v in list(facts.items())[:8]))
    prefs = p.get('preferences') or {}
    if prefs:
        out.append('Preferencias: ' + '; '.join(f'{k}={v}' for k, v in list(prefs.items())[:8]))
    g = primary_goal(ctx)
    if g:
        out.append(f"Objetivo principal: [{g.get('id')}] {g.get('title')} | progresso={g.get('progress',0)}% | prazo={g.get('deadline') or 'nao definido'}")
    tasks = ranked_tasks(ctx)
    if tasks:
        out.append('Tarefas pendentes: ' + ' | '.join(f"[{t.get('id')}] {t.get('title')} ({t.get('priority','medium')})" for t in tasks[:max_items]))
    opp = best_opportunity(ctx)
    if opp:
        out.append(f"Melhor oportunidade: {opp.get('title')} | score={opp.get('score',0)}/100")
    return '\n'.join(out)
