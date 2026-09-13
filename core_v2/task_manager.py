#!/usr/bin/env python3
from __future__ import annotations

import json, time, uuid
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / '.hermes/core-v2/state'
FILE = STATE_DIR / 'tasks.json'


def _load() -> dict[str, Any]:
    try: return json.loads(FILE.read_text(encoding='utf-8'))
    except Exception: return {'tasks': []}


def _save(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def list_tasks(status: str | None = None, goal_id: str | None = None) -> list[dict[str, Any]]:
    rows = list(_load().get('tasks') or [])
    if status: rows = [x for x in rows if x.get('status') == status]
    if goal_id: rows = [x for x in rows if x.get('goal_id') == goal_id]
    return rows


def create_task(title: str, *, goal_id: str | None = None, priority: str = 'medium',
                due: str | None = None, kind: str = 'action', metadata: dict | None = None) -> dict[str, Any]:
    title = title.strip()
    if not title: raise ValueError('task title required')
    data = _load(); now = int(time.time())
    task = {'id': uuid.uuid4().hex[:10], 'title': title, 'status': 'todo', 'priority': priority,
            'goal_id': goal_id, 'due': due, 'kind': kind, 'metadata': metadata or {},
            'created_at': now, 'updated_at': now}
    data.setdefault('tasks', []).append(task); _save(data); return task


def update_task(ref: str, **changes: Any) -> dict[str, Any]:
    data = _load(); key = ref.strip().casefold()
    for i, task in enumerate(data.get('tasks') or []):
        if str(task.get('id','')).casefold().startswith(key) or str(task.get('title','')).casefold() == key:
            merged = dict(task); merged.update({k:v for k,v in changes.items() if v is not None}); merged['updated_at'] = int(time.time())
            data['tasks'][i] = merged; _save(data); return merged
    raise KeyError(ref)


def complete_task(ref: str) -> dict[str, Any]:
    return update_task(ref, status='done', completed_at=int(time.time()))


def summary(status: str = 'todo') -> str:
    rows = list_tasks(status=status)
    if not rows: return 'Nenhuma tarefa pendente.' if status == 'todo' else 'Nenhuma tarefa encontrada.'
    rank = {'high':0,'medium':1,'low':2}; rows.sort(key=lambda x: rank.get(x.get('priority','medium'),1))
    out = ['Tarefas pendentes:' if status == 'todo' else f'Tarefas ({status}):']
    for t in rows[-30:]:
        due = f" | prazo={t['due']}" if t.get('due') else ''
        out.append(f"- [{t['id']}] {t['title']} | {t.get('priority','medium')}{due}")
    return '\n'.join(out)
