#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime
from lead_manager import list_leads


def hot_leads(limit: int = 5):
    rows = [x for x in list_leads(None) if x.get('stage') not in {'won','lost'}]
    return sorted(rows, key=lambda x: int(x.get('score',0)), reverse=True)[:limit]


def followups_due(limit: int = 10):
    now = datetime.now()
    out=[]
    for lead in list_leads(None):
        raw = str(lead.get('next_followup_at') or '').strip()
        if not raw: continue
        try: due = datetime.fromisoformat(raw)
        except Exception: continue
        if due <= now and lead.get('stage') not in {'won','lost'}: out.append(lead)
    return out[:limit]


def summary() -> str:
    rows = list_leads(None)
    if not rows: return 'CRM vazio. Ainda não há leads registrados.'
    stages={}
    for x in rows: stages[x.get('stage','new')] = stages.get(x.get('stage','new'),0)+1
    hot = hot_leads(3); due = followups_due(5)
    out=['CRM — visão rápida:']
    out.append('- Pipeline: ' + ', '.join(f'{k}={v}' for k,v in sorted(stages.items())))
    if hot:
        out.append('Leads mais quentes:')
        for x in hot: out.append(f"- {x.get('name')} | score={x.get('score',0)} | {x.get('stage')}")
    if due:
        out.append('Follow-ups vencidos/agora:')
        for x in due: out.append(f"- {x.get('name')} | {x.get('next_followup_at')}")
    return '\n'.join(out)
