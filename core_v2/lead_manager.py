#!/usr/bin/env python3
from __future__ import annotations

import json, time, uuid
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / '.hermes/core-v2/state'
FILE = STATE_DIR / 'leads.json'

STAGES = ('new','qualified','contact_ready','contacted','replied','proposal','won','lost')


def _load() -> dict[str, Any]:
    try: return json.loads(FILE.read_text(encoding='utf-8'))
    except Exception: return {'leads': []}


def _save(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def add_lead(name: str, *, website: str = '', niche: str = '', contact: str = '',
             problem: str = '', offer: str = '', estimated_value: float | None = None,
             source: str = 'manual', score: int = 50, notes: str = '') -> dict[str, Any]:
    data = _load(); now = int(time.time())
    lead = {'id': uuid.uuid4().hex[:10], 'name': name.strip(), 'website': website.strip(),
            'niche': niche.strip(), 'contact': contact.strip(), 'problem': problem.strip(),
            'offer': offer.strip(), 'estimated_value': estimated_value, 'source': source,
            'score': max(0,min(100,int(score))), 'stage': 'new', 'notes': notes,
            'last_contact_at': None, 'next_followup_at': None,
            'created_at': now, 'updated_at': now}
    data.setdefault('leads', []).append(lead); _save(data); return lead


def list_leads(stage: str | None = None) -> list[dict[str, Any]]:
    rows = list(_load().get('leads') or [])
    if stage: rows = [x for x in rows if x.get('stage') == stage]
    return sorted(rows, key=lambda x: (int(x.get('score',0)), int(x.get('updated_at',0))), reverse=True)


def get_lead(ref: str) -> dict[str, Any] | None:
    key = ref.strip().casefold()
    for lead in list_leads(None):
        if str(lead.get('id','')).casefold().startswith(key) or str(lead.get('name','')).casefold() == key:
            return lead
    return None


def update_lead(ref: str, **changes: Any) -> dict[str, Any]:
    data = _load(); key = ref.strip().casefold()
    for i, lead in enumerate(data.get('leads') or []):
        if str(lead.get('id','')).casefold().startswith(key) or str(lead.get('name','')).casefold() == key:
            merged = dict(lead)
            for k,v in changes.items():
                if v is not None: merged[k] = v
            if merged.get('stage') not in STAGES: merged['stage'] = lead.get('stage','new')
            merged['updated_at'] = int(time.time()); data['leads'][i] = merged; _save(data); return merged
    raise KeyError(ref)


def record_contact(ref: str, *, next_followup_at: str | None = None) -> dict[str, Any]:
    return update_lead(ref, stage='contacted', last_contact_at=int(time.time()), next_followup_at=next_followup_at)


def summary(limit: int = 12) -> str:
    rows = list_leads(None)
    if not rows: return 'Nenhum lead registrado ainda.'
    out = [f'Pipeline de leads: {len(rows)} total']
    for x in rows[:limit]:
        value = f" | R$ {float(x['estimated_value']):,.0f}".replace(',', '.') if x.get('estimated_value') else ''
        out.append(f"- [{x['id']}] {x['name']} | {x.get('stage')} | score={x.get('score',0)}{value}")
    return '\n'.join(out)
