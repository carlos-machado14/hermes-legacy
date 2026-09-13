#!/usr/bin/env python3
from __future__ import annotations

import json, time
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / '.hermes/core-v2/state'
FILE = STATE_DIR / 'learning.json'


def _load() -> dict[str, Any]:
    try: return json.loads(FILE.read_text(encoding='utf-8'))
    except Exception: return {'events': [], 'signals': {}}


def _save(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def record_outcome(category: str, label: str, success: bool, *, value: float | None = None, notes: str = '') -> dict[str, Any]:
    data=_load(); event={'ts':int(time.time()),'category':category,'label':label,'success':bool(success),'value':value,'notes':notes}
    data.setdefault('events',[]).append(event); data['events']=data['events'][-1000:]
    key=f'{category}:{label}'.casefold(); sig=data.setdefault('signals',{}).setdefault(key,{'wins':0,'losses':0,'value':0.0})
    sig['wins' if success else 'losses'] += 1
    if value: sig['value'] = float(sig.get('value',0.0)) + float(value)
    _save(data); return event


def ranked_signals(limit: int = 10) -> list[dict[str, Any]]:
    rows=[]
    for key,s in (_load().get('signals') or {}).items():
        wins=int(s.get('wins',0)); losses=int(s.get('losses',0)); total=wins+losses
        rows.append({'key':key,'wins':wins,'losses':losses,'rate':round((wins/total)*100) if total else 0,'value':s.get('value',0)})
    return sorted(rows,key=lambda x:(x['rate'],x['wins'],x['value']),reverse=True)[:limit]


def summary() -> str:
    rows=ranked_signals()
    if not rows: return 'Ainda não há resultados suficientes para o Hermes aprender padrões.'
    out=['Aprendizados mais fortes:']
    for x in rows: out.append(f"- {x['key']} | acerto={x['rate']}% | {x['wins']} ganhos / {x['losses']} perdas | valor={x['value']}")
    return '\n'.join(out)
