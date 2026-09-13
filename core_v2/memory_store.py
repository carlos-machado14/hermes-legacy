#!/usr/bin/env python3
from __future__ import annotations
import json, time
from pathlib import Path
from typing import Any

ROOT = Path.home() / '.hermes/core-v2/state'
EVENTS = ROOT / 'operational_memory.jsonl'
PREFS = ROOT / 'preferences.json'
MAX_EVENTS = 2000


def _ensure() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)


def remember(kind: str, summary: str, details: dict[str, Any] | None = None, ok: bool | None = None) -> dict[str, Any]:
    _ensure()
    event = {
        'ts': int(time.time()),
        'kind': kind,
        'summary': summary,
        'details': details or {},
    }
    if ok is not None:
        event['ok'] = bool(ok)
    with EVENTS.open('a', encoding='utf-8') as f:
        f.write(json.dumps(event, ensure_ascii=False) + '\n')
    _trim()
    return event


def _trim() -> None:
    try:
        lines = EVENTS.read_text(encoding='utf-8').splitlines()
        if len(lines) > MAX_EVENTS:
            EVENTS.write_text('\n'.join(lines[-MAX_EVENTS:]) + '\n', encoding='utf-8')
    except Exception:
        pass


def recent(limit: int = 20, kind: str | None = None) -> list[dict[str, Any]]:
    try:
        rows = []
        for line in EVENTS.read_text(encoding='utf-8').splitlines():
            try:
                item = json.loads(line)
                if kind is None or item.get('kind') == kind:
                    rows.append(item)
            except Exception:
                continue
        return rows[-max(1, min(limit, 100)):]
    except Exception:
        return []


def set_preference(key: str, value: Any) -> None:
    _ensure()
    try:
        data = json.loads(PREFS.read_text(encoding='utf-8'))
    except Exception:
        data = {}
    data[key] = value
    PREFS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def get_preferences() -> dict[str, Any]:
    try:
        return json.loads(PREFS.read_text(encoding='utf-8'))
    except Exception:
        return {}
