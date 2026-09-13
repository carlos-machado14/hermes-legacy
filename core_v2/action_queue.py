#!/usr/bin/env python3
from __future__ import annotations

import json, time, uuid
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / '.hermes/core-v2/state'
FILE = STATE_DIR / 'action_queue.json'


def _load() -> dict[str, Any]:
    try:
        data = json.loads(FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {'actions': []}
    except Exception:
        return {'actions': []}


def _save(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def list_actions(status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows = list(_load().get('actions') or [])
    if status:
        rows = [x for x in rows if x.get('status') == status]
    return rows[-limit:]


def get_action(ref: str) -> dict[str, Any] | None:
    key = str(ref or '').strip().casefold()
    for action in reversed(list_actions(None, 1000)):
        if str(action.get('id','')).casefold().startswith(key):
            return action
    return None


def add_action(title: str, *, kind: str, task_id: str | None = None, goal_id: str | None = None,
               risk: str = 'low', requires_approval: bool = False, payload: dict | None = None) -> dict[str, Any]:
    data = _load(); now = int(time.time())
    action = {
        'id': uuid.uuid4().hex[:10], 'title': title.strip(), 'kind': kind,
        'task_id': task_id, 'goal_id': goal_id, 'risk': risk,
        'requires_approval': bool(requires_approval),
        'status': 'pending_approval' if requires_approval else 'queued',
        'payload': payload or {}, 'result': None, 'error': None,
        'created_at': now, 'updated_at': now,
    }
    data.setdefault('actions', []).append(action)
    data['actions'] = data['actions'][-1000:]
    _save(data); return action


def update_action(ref: str, **changes: Any) -> dict[str, Any]:
    data = _load(); key = str(ref or '').strip().casefold()
    for i, action in enumerate(data.get('actions') or []):
        if str(action.get('id','')).casefold().startswith(key):
            merged = dict(action); merged.update(changes); merged['updated_at'] = int(time.time())
            data['actions'][i] = merged; _save(data); return merged
    raise KeyError(ref)


def approve(ref: str) -> dict[str, Any]:
    action = get_action(ref)
    if not action: raise KeyError(ref)
    if action.get('status') not in {'pending_approval','queued'}: return action
    return update_action(action['id'], status='approved', approved_at=int(time.time()))


def reject(ref: str) -> dict[str, Any]:
    action = get_action(ref)
    if not action: raise KeyError(ref)
    return update_action(action['id'], status='rejected', rejected_at=int(time.time()))


def summary(limit: int = 15) -> str:
    rows = list_actions(None, limit)
    if not rows: return 'Nenhuma ação autônoma registrada.'
    out = ['Ações autônomas recentes:']
    for a in rows:
        approval = ' | precisa aprovação' if a.get('requires_approval') and a.get('status') == 'pending_approval' else ''
        out.append(f"- [{a.get('id')}] {a.get('title')} | {a.get('status')} | risco={a.get('risk')}{approval}")
    return '\n'.join(out)
