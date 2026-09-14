from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

ROOT = Path.home() / '.hermes' / 'core-v2'
PATH = ROOT / 'state' / 'audit.jsonl'


def record(event: str, **data: Any) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {'ts': int(time.time()), 'event': event, **data}
    with PATH.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')


def recent(limit: int = 100) -> list[dict[str, Any]]:
    if not PATH.exists():
        return []
    lines = PATH.read_text(encoding='utf-8', errors='ignore').splitlines()[-max(1, limit):]
    out: list[dict[str, Any]] = []
    for line in lines:
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                out.append(item)
        except Exception:
            continue
    return out
