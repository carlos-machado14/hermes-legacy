#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from autonomy_settings import load as load_autonomy_settings
from decision_log import recent as recent_decisions, record
from delivery import channel, send_telegram
from goal_execution_engine import run_cycle
from goal_manager import list_goals
from initiative_engine import discover as discover_initiatives
from proactive_engine import daily_brief, weekly_review, recommendation
from proactive_settings import load as load_settings
from task_manager import list_tasks
from time_store import occurrence_stats

ROOT = Path.home() / '.hermes/core-v2'
STATE_DIR = ROOT / 'state'
RUNTIME_FILE = STATE_DIR / 'autonomous_runtime.json'


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        data=json.loads(path.read_text(encoding='utf-8')); return data if isinstance(data,dict) else fallback
    except Exception: return fallback


def _write_json(path: Path, data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def _send(text: str) -> bool:
    ok,_=send_telegram(text,attempts=2); return ok


def _quiet(settings: dict[str, Any], now: datetime) -> bool:
    start=int(settings.get('quiet_start_hour',22))%24; end=int(settings.get('quiet_end_hour',7))%24; h=now.hour
    if start==end: return False
    return h>=start or h<end if start>end else start<=h<end


def _last_progress_ts() -> int:
    rows=recent_decisions(150); kinds={'task_completed','goal_progress','goal_completed','next_action','decision','autonomous_action_completed'}
    return max([int(x.get('ts') or 0) for x in rows if x.get('kind') in kinds], default=0)


def _overdue_high_tasks() -> list[dict[str, Any]]:
    today=datetime.now().date(); out=[]
    for task in list_tasks(status='todo'):
        if task.get('priority')!='high' or not task.get('due'): continue
        try: due=datetime.fromisoformat(str(task.get('due')).strip()).date()
        except Exception: continue
        if due<today: out.append(task)
    return out


def _slot(runtime: dict[str, Any], key: str, stamp: str) -> bool: return runtime.get(key)!=stamp

def _mark(runtime: dict[str, Any], key: str, stamp: Any) -> None:
    runtime[key]=stamp; runtime['updated_at']=int(time.time()); _write_json(RUNTIME_FILE,runtime)


def _initiative_cycle(runtime: dict[str, Any]) -> list[dict[str, Any]]:
    bucket=int(time.time()//(6*3600))
    if runtime.get('initiative_bucket')==bucket: return []
    created=discover_initiatives(limit=5)
    runtime['initiative_bucket']=bucket; runtime['updated_at']=int(time.time()); _write_json(RUNTIME_FILE,runtime)
    if created: record('initiative_discovery',f'{len(created)} ação(ões) autônoma(s) criada(s) a partir dos objetivos.')
    return created


def _autonomy_cycle(runtime: dict[str, Any]) -> bool:
    settings=load_autonomy_settings()
    if not settings.get('enabled'): return False
    _initiative_cycle(runtime)
    minutes=max(5,int(settings.get('cycle_minutes',30))); bucket=int(time.time()//(minutes*60))
    if runtime.get('autonomy_bucket')==bucket: return False
    report=run_cycle(); _mark(runtime,'autonomy_bucket',bucket)
    executed=report.get('executed') or []; waiting=report.get('waiting_approval') or []
    if not executed and not waiting: return False
    lines=['🤖 Hermes — avancei sozinho nas suas prioridades']
    if executed:
        lines.append('\nConcluí:')
        for action in executed[:5]: lines.append(f"- {action.get('title')}")
    pending=[a for a in waiting if a.get('status')=='pending_approval']
    if pending:
        lines.append('\nPreciso da sua aprovação antes de continuar:')
        for action in pending[:5]: lines.append(f"- [{action.get('id')}] {action.get('title')}")
    return _send('\n'.join(lines))


def tick() -> None:
    proactive=load_settings(); autonomy=load_autonomy_settings()
    if not proactive.get('enabled') and not autonomy.get('enabled'): return
    if not channel(): return
    now=datetime.now(); runtime=_read_json(RUNTIME_FILE,{})
    quiet=_quiet(proactive,now)

    if autonomy.get('enabled') and not quiet:
        if _autonomy_cycle(runtime): return
    if not proactive.get('enabled'): return

    day=now.strftime('%Y-%m-%d'); week=now.strftime('%G-W%V')
    morning=int(proactive.get('morning_hour',8))%24; evening=int(proactive.get('evening_hour',19))%24
    weekly_day=int(proactive.get('weekly_review_weekday',6))%7; weekly_hour=int(proactive.get('weekly_review_hour',18))%24

    if now.hour==morning and _slot(runtime,'morning_sent',day):
        if _send('☀️ Hermes — plano do dia\n\n'+daily_brief()): record('proactive_brief','Brief da manhã enviado.'); _mark(runtime,'morning_sent',day)
        return
    if now.weekday()==weekly_day and now.hour==weekly_hour and _slot(runtime,'weekly_sent',week):
        if _send('📊 Hermes — revisão semanal\n\n'+weekly_review()): record('proactive_review','Revisão semanal enviada.'); _mark(runtime,'weekly_sent',week)
        return
    if now.hour==evening and _slot(runtime,'evening_sent',day):
        if _send('🌙 Hermes — fechamento do dia\n\n'+weekly_review()): record('proactive_review','Fechamento do dia enviado.'); _mark(runtime,'evening_sent',day)
        return
    if quiet: return

    stats=occurrence_stats(int(time.time())-86400)
    if stats.get('failed',0)>0 and _slot(runtime,'schedule_failure_alert',day):
        if _send(f"⚠️ Detectei {stats['failed']} falha(s) de entrega em lembretes nas últimas 24h. Vou continuar monitorando; consulte 'status das rotinas' para diagnóstico."):
            _mark(runtime,'schedule_failure_alert',day)
        return

    overdue=_overdue_high_tasks()
    if overdue and _slot(runtime,'overdue_alert',day):
        lines=['⚠️ Hermes — há tarefas importantes atrasadas:']+[f"- {t.get('title')}" for t in overdue[:5]]+['\nQuer que eu reorganize suas prioridades?']
        if _send('\n'.join(lines)): record('proactive_alert',f'{len(overdue)} tarefa(s) de alta prioridade atrasada(s).'); _mark(runtime,'overdue_alert',day)
        return

    goals=list_goals(include_done=False); stall_hours=max(1,int(proactive.get('stall_hours',24))); last_progress=_last_progress_ts()
    if goals and last_progress and time.time()-last_progress>=stall_hours*3600 and _slot(runtime,'stall_alert',day):
        if _send('🧭 Hermes — seus objetivos estão sem avanço recente.\n\n'+recommendation()):
            record('proactive_alert','Objetivo sem avanço recente; recomendação enviada.'); _mark(runtime,'stall_alert',day)


def main() -> int:
    print('Hermes Autonomous Assistant v5 ativo',flush=True)
    while True:
        try: tick()
        except Exception as exc: print(f'autonomous tick error: {exc}',flush=True)
        time.sleep(60)

if __name__=='__main__': raise SystemExit(main())
