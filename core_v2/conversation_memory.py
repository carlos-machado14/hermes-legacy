#!/usr/bin/env python3
from __future__ import annotations

import json, time
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / '.hermes/core-v2/state'
FILE = STATE_DIR / 'conversation.json'
MAX_ITEMS = 40


def _load() -> dict[str, Any]:
    try:
        data = json.loads(FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {'items': []}
    except Exception:
        return {'items': []}


def _save(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data['items'] = list(data.get('items') or [])[-MAX_ITEMS:]
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def add(role: str, text: str) -> None:
    text = str(text or '').strip()
    if not text:
        return
    data = _load()
    data.setdefault('items', []).append({'ts': int(time.time()), 'role': role, 'text': text[:6000]})
    _save(data)


def recent(limit: int = 8) -> list[dict[str, Any]]:
    return list(_load().get('items') or [])[-max(1, limit):]


def compact(limit: int = 8, max_chars: int = 5000) -> str:
    rows = recent(limit)
    out: list[str] = []
    for row in rows:
        who = 'Usuário' if row.get('role') == 'user' else 'Hermes'
        out.append(f"{who}: {row.get('text','')}")
    text = '\n'.join(out)
    return text[-max_chars:]


def clear() -> None:
    _save({'items': []})
