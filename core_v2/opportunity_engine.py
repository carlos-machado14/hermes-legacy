#!/usr/bin/env python3
from __future__ import annotations

import json, time, uuid
from pathlib import Path
from typing import Any

from personal_memory import profile

STATE_DIR = Path.home() / '.hermes/core-v2/state'
FILE = STATE_DIR / 'opportunities.json'


def _load() -> dict[str, Any]:
    try: return json.loads(FILE.read_text(encoding='utf-8'))
    except Exception: return {'opportunities': []}


def _save(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def score(item: dict[str, Any]) -> int:
    revenue = max(0, min(10, int(item.get('revenue_score', 5))))
    speed = max(0, min(10, int(item.get('speed_score', 5))))
    fit = max(0, min(10, int(item.get('fit_score', 5))))
    cost = max(0, min(10, int(item.get('cost_score', 5))))
    risk = max(0, min(10, int(item.get('risk_score', 5))))
    return round(revenue*3 + speed*2 + fit*3 + (10-cost) + (10-risk))


def add(title: str, *, source: str = 'manual', revenue_score: int = 5, speed_score: int = 5,
        fit_score: int = 5, cost_score: int = 5, risk_score: int = 5, notes: str = '') -> dict[str, Any]:
    data = _load(); item = {
        'id': uuid.uuid4().hex[:10], 'title': title.strip(), 'source': source, 'status': 'open',
        'revenue_score': revenue_score, 'speed_score': speed_score, 'fit_score': fit_score,
        'cost_score': cost_score, 'risk_score': risk_score, 'notes': notes, 'created_at': int(time.time())}
    item['score'] = score(item); data.setdefault('opportunities', []).append(item); _save(data); return item


def list_items(status: str | None = 'open') -> list[dict[str, Any]]:
    rows = list(_load().get('opportunities') or [])
    if status: rows = [x for x in rows if x.get('status') == status]
    return sorted(rows, key=lambda x: int(x.get('score', 0)), reverse=True)


def seed_from_profile() -> list[dict[str, Any]]:
    p = profile(); skills = [s.casefold() for s in p.get('skills') or []]
    suggestions: list[tuple[str,int,int,int,int,int]] = []
    joined = ' '.join(skills)
    if any(k in joined for k in ('flutter','mobile','app')):
        suggestions += [
            ('Oferecer MVPs mobile/web rápidos para pequenas empresas', 8, 8, 10, 2, 4),
            ('Pacote de manutenção e evolução mensal de apps Flutter', 7, 7, 10, 2, 3),
        ]
    if any(k in joined for k in ('site','web','frontend','landing')):
        suggestions += [
            ('Prospecção de empresas com site antigo para vender redesign/landing page', 8, 9, 9, 2, 4),
            ('Landing pages por nicho com template reutilizável', 7, 9, 9, 2, 3),
        ]
    if not suggestions:
        suggestions = [
            ('Vender um serviço baseado na habilidade profissional mais forte', 7, 8, 6, 2, 4),
            ('Criar um microproduto digital para um problema recorrente de um nicho conhecido', 7, 5, 5, 4, 6),
        ]
    existing = {x.get('title','').casefold() for x in list_items(None)}; created=[]
    for title,rev,spd,fit,cost,risk in suggestions:
        if title.casefold() not in existing: created.append(add(title, source='profile', revenue_score=rev, speed_score=spd, fit_score=fit, cost_score=cost, risk_score=risk))
    return created


def summary(limit: int = 10) -> str:
    rows = list_items()[:limit]
    if not rows: return 'Nenhuma oportunidade registrada ainda.'
    out=['Oportunidades priorizadas:']
    for x in rows: out.append(f"- [{x['id']}] {x['title']} | score={x.get('score',0)}/100")
    return '\n'.join(out)
