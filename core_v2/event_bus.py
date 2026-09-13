#!/usr/bin/env python3
from __future__ import annotations
import json, time
from pathlib import Path
from typing import Any
from memory_store import remember

QUEUE = Path.home() / '.hermes/core-v2/state/events.jsonl'


def publish(event_type: str, payload: dict[str, Any] | None = None, source: str = 'core') -> dict[str, Any]:
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    event = {'id': f'{int(time.time()*1000)}-{event_type}', 'ts': int(time.time()), 'type': event_type, 'source': source, 'payload': payload or {}}
    with QUEUE.open('a', encoding='utf-8') as f:
        f.write(json.dumps(event, ensure_ascii=False) + '\n')
    remember('event', event_type, event)
    return event


def recent(limit: int = 50) -> list[dict[str, Any]]:
    try:
        rows = []
        for line in QUEUE.read_text(encoding='utf-8').splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
        return rows[-max(1, min(limit, 200)):]
    except Exception:
        return []
