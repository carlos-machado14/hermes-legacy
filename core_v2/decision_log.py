#!/usr/bin/env python3
from __future__ import annotations

import json, time
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / '.hermes/core-v2/state'
FILE = STATE_DIR / 'decisions.json'


def _load() -> dict[str, Any]:
    try:
        return json.loads(FILE.read_text(encoding='utf-8'))
    except Exception:
        return {'items': []}


def _save(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def record(kind: str, summary: str, *, metadata: dict | None = None) -> dict[str, Any]:
    data = _load()
    item = {'ts': int(time.time()), 'kind': kind, 'summary': summary.strip(), 'metadata': metadata or {}}
    data.setdefault('items', []).append(item)
    data['items'] = data['items'][-500:]
    _save(data)
    return item


def recent(limit: int = 20, kind: str | None = None) -> list[dict[str, Any]]:
    rows = list(_load().get('items') or [])
    if kind:
        rows = [x for x in rows if x.get('kind') == kind]
    return rows[-limit:]


def summary(limit: int = 10) -> str:
    rows = recent(limit)
    if not rows:
        return 'Nenhuma decisão registrada ainda.'
    out = ['Decisões recentes:']
    for row in rows:
        stamp = time.strftime('%d/%m %H:%M', time.localtime(int(row.get('ts', 0))))
        out.append(f"- {stamp} [{row.get('kind','decision')}] {row.get('summary','')}")
    return '\n'.join(out)
