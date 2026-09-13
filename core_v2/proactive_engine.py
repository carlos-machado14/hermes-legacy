#!/usr/bin/env python3
from __future__ import annotations

from context_builder import snapshot, primary_goal, ranked_tasks, best_opportunity
from decision_log import record, summary as decisions_summary


def daily_brief() -> str:
    ctx = snapshot(); goal = primary_goal(ctx); tasks = ranked_tasks(ctx); opp = best_opportunity(ctx)
    out = ['Prioridade de hoje:']
    if goal:
        out.append(f"Objetivo principal: {goal.get('title')} ({goal.get('progress',0)}%)")
    if tasks:
        out.append('Ações prioritárias:')
        for i, task in enumerate(tasks[:5], 1):
            out.append(f"{i}. {task.get('title')}")
    else:
        out.append('Nenhuma tarefa pendente registrada.')
    if opp:
        out.append(f"Melhor oportunidade atual: {opp.get('title')} (score {opp.get('score',0)}/100)")
    if tasks:
        record('next_action', tasks[0].get('title',''), metadata={'task_id': tasks[0].get('id')})
        out.append(f"Próxima ação recomendada: {tasks[0].get('title')}")
    return '\n'.join(out)


def weekly_review() -> str:
    ctx = snapshot(); goals = ctx.get('goals') or []; tasks = ranked_tasks(ctx); opp = best_opportunity(ctx)
    out = ['Revisão atual:']
    if goals:
        for g in goals[:5]: out.append(f"- Objetivo: {g.get('title')} | progresso={g.get('progress',0)}% | prazo={g.get('deadline') or 'não definido'}")
    else: out.append('- Nenhum objetivo ativo.')
    out.append(f"- Tarefas pendentes: {len(tasks)}")
    high = [t for t in tasks if t.get('priority') == 'high']
    if high: out.append(f"- Alta prioridade: {len(high)}")
    if opp: out.append(f"- Melhor oportunidade: {opp.get('title')} ({opp.get('score',0)}/100)")
    if tasks: out.append(f"- Recomendo focar agora em: {tasks[0].get('title')}")
    return '\n'.join(out)


def recommendation() -> str:
    ctx = snapshot(); goal = primary_goal(ctx); tasks = ranked_tasks(ctx); opp = best_opportunity(ctx)
    out = ['Minha recomendação agora:']
    if goal: out.append(f"1. Mantenha foco no objetivo: {goal.get('title')}.")
    if tasks: out.append(f"2. Execute primeiro: {tasks[0].get('title')}.")
    if opp: out.append(f"3. A oportunidade mais forte é: {opp.get('title')} (score {opp.get('score',0)}/100).")
    if not tasks: out.append('2. Crie tarefas concretas ligadas ao objetivo principal.')
    out.append('Evite abrir novas frentes até concluir a próxima ação prioritária.')
    return '\n'.join(out)


def continue_last() -> str:
    from decision_log import recent
    rows = recent(20, kind='next_action')
    if not rows:
        return 'Ainda não há uma próxima ação registrada. Pergunte "o que devo fazer hoje?" para eu definir uma.'
    item = rows[-1]
    return f"Vamos continuar pela próxima ação definida: {item.get('summary')}.\nSe quiser, diga \"execute essa ação\" ou me informe o resultado para eu atualizar o plano."


def history() -> str:
    return decisions_summary(10)
