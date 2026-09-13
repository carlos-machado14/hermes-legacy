#!/usr/bin/env python3
from __future__ import annotations

import json, re, time, uuid
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / '.hermes/core-v2/state'
FILE = STATE_DIR / 'goals.json'


def _load() -> dict[str, Any]:
    try:
        return json.loads(FILE.read_text(encoding='utf-8'))
    except Exception:
        return {'goals': []}


def _save(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def list_goals(include_done: bool = True) -> list[dict[str, Any]]:
    rows = list(_load().get('goals') or [])
    return rows if include_done else [g for g in rows if g.get('status') != 'done']


def get_goal(ref: str) -> dict[str, Any] | None:
    key = ref.strip().casefold()
    for g in list_goals():
        if str(g.get('id', '')).casefold().startswith(key) or str(g.get('title', '')).casefold() == key:
            return g
    return None


def create_goal(title: str, *, target_value: float | None = None, target_unit: str | None = None,
                deadline: str | None = None, category: str = 'general', notes: str = '') -> dict[str, Any]:
    title = title.strip()
    if not title:
        raise ValueError('goal title required')
    data = _load()
    now = int(time.time())
    goal = {
        'id': uuid.uuid4().hex[:10], 'title': title, 'category': category,
        'status': 'active', 'progress': 0, 'target_value': target_value,
        'target_unit': target_unit, 'deadline': deadline, 'notes': notes,
        'created_at': now, 'updated_at': now,
    }
    data.setdefault('goals', []).append(goal)
    _save(data)
    return goal


def update_goal(ref: str, **changes: Any) -> dict[str, Any]:
    data = _load(); key = ref.strip().casefold()
    for i, g in enumerate(data.get('goals') or []):
        if str(g.get('id', '')).casefold().startswith(key) or str(g.get('title', '')).casefold() == key:
            merged = dict(g); merged.update({k: v for k, v in changes.items() if v is not None})
            merged['updated_at'] = int(time.time()); data['goals'][i] = merged; _save(data); return merged
    raise KeyError(ref)


def complete_goal(ref: str) -> dict[str, Any]:
    return update_goal(ref, status='done', progress=100)


def infer_money_goal(text: str) -> dict[str, Any] | None:
    t = text.lower()
    if not any(k in t for k in ('ganhar', 'faturar', 'renda', 'receita')):
        return None
    m = re.search(r'(?:r\$\s*)?([\d\.]+(?:,\d+)?)\s*(?:reais|real|r\$)?', t)
    value = None
    if m:
        raw = m.group(1).replace('.', '').replace(',', '.')
        try: value = float(raw)
        except Exception: pass
    days = re.search(r'(\d+)\s*dias?', t)
    deadline = f'{days.group(1)} dias' if days else None
    title = text.strip().rstrip('.!?')
    return {'title': title, 'target_value': value, 'target_unit': 'BRL' if value else None,
            'deadline': deadline, 'category': 'money'}


def summary() -> str:
    rows = list_goals(False)
    if not rows: return 'Nenhum objetivo ativo.'
    out = ['Objetivos ativos:']
    for g in rows[-20:]:
        target = f" | meta={g['target_value']} {g.get('target_unit') or ''}" if g.get('target_value') else ''
        deadline = f" | prazo={g['deadline']}" if g.get('deadline') else ''
        out.append(f"- [{g['id']}] {g['title']} | {g.get('progress',0)}%{target}{deadline}")
    return '\n'.join(out)
