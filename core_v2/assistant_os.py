from __future__ import annotations

from datetime import datetime
from typing import Any

from context_builder import snapshot as context_snapshot
from goal_manager import list_goals
from job_store import list_jobs
from project_registry import list_projects
from resource_manager import snapshot as resource_snapshot
from task_manager import list_tasks
from time_store import list_schedules, occurrence_stats, tz


def snapshot() -> dict[str, Any]:
    tasks=list_tasks(); goals=list_goals(); jobs=list_jobs(None,30); projects=list_projects(); schedules=list_schedules(status='active',limit=50)
    pending=[x for x in tasks if str(x.get('status') or '').casefold() not in {'done','completed','concluida','concluído','concluido'}]
    active_jobs=[x for x in jobs if x.get('status') not in {'done','cancelled'}]
    return {
        'context':context_snapshot(),
        'tasks':{'pending':pending[:20],'total_pending':len(pending)},
        'goals':goals[:20],
        'jobs':{'active':active_jobs[:20],'total_active':len(active_jobs)},
        'schedules':{'active':schedules[:20],'total_active':len(schedules)},
        'projects':projects[:20],
        'resources':resource_snapshot(),
        'delivery':occurrence_stats(),
    }


def brief() -> str:
    s=snapshot(); lines=['Hermes Assistant OS — panorama atual']
    lines.append(f"Tarefas pendentes: {s['tasks']['total_pending']}")
    for item in s['tasks']['pending'][:5]: lines.append(f"- {item.get('title') or item.get('name') or 'Tarefa'}")
    lines.append(f"Fluxos ativos: {s['jobs']['total_active']}")
    for item in s['jobs']['active'][:4]: lines.append(f"- [{item.get('id')}] {item.get('status')} — {item.get('title')}")
    lines.append(f"Agenda/rotinas ativas: {s['schedules']['total_active']}")
    for item in s['schedules']['active'][:4]:
        when=''
        if item.get('next_run_at'):
            dt=datetime.fromtimestamp(int(item['next_run_at']),tz(item.get('timezone')))
            when=f" — próximo {dt.strftime('%d/%m %H:%M')}"
        lines.append(f"- {item.get('message')}{when}")
    lines.append(f"Objetivos cadastrados: {len(s['goals'])}")
    lines.append(f"Projetos monitorados: {len(s['projects'])}")
    r=s['resources']; lines.append(f"VPS: CPU {r['cpu_percent']}% | RAM {r['memory_percent']}% | livre {r['memory_available_mb']} MB")
    d=s['delivery']
    if d.get('failed'): lines.append(f"Atenção: {d['failed']} entrega(s) de lembrete falharam nas últimas 24h.")
    return '\n'.join(lines)


def attention() -> str:
    s=snapshot(); items=[]
    for job in [j for j in s['jobs']['active'] if j.get('status') in {'needs_attention','blocked','failed'}][:5]:
        items.append(f"Fluxo [{job.get('id')}] precisa de atenção: {job.get('error') or job.get('title')}")
    for task in s['tasks']['pending'][:8]:
        if str(task.get('priority') or '').casefold() in {'high','urgent','alta','urgente'}:
            items.append(f"Tarefa prioritária: {task.get('title') or task.get('name')}")
    if s['delivery'].get('failed',0)>0: items.append(f"{s['delivery']['failed']} lembrete(s) tiveram falha definitiva de entrega nas últimas 24h")
    r=s['resources']
    if r['memory_percent']>=85: items.append(f"RAM elevada na VPS: {r['memory_percent']}%")
    if r['cpu_percent']>=90: items.append(f"CPU elevada na VPS: {r['cpu_percent']}%")
    if not items: items.append('Nenhum bloqueio crítico detectado no estado local.')
    return 'O que precisa da sua atenção:\n'+'\n'.join(f'- {x}' for x in items)
