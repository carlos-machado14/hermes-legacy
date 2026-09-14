#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path.home() / '.hermes' / 'core-v2'
LOG_DIR = ROOT / 'logs'
PERF_LOG = LOG_DIR / 'perf.jsonl'
_LOCK = threading.Lock()


def trace_id() -> str:
    existing = (os.getenv('HERMES_TRACE_ID') or '').strip()
    if existing:
        return existing[:64]
    value = uuid.uuid4().hex[:12]
    os.environ['HERMES_TRACE_ID'] = value
    return value


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe(v) for v in value]
    return str(value)


def emit(stage: str, *, elapsed_ms: float | None = None, **fields: Any) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        'ts': time.time(),
        'trace_id': trace_id(),
        'stage': str(stage),
    }
    if elapsed_ms is not None:
        row['elapsed_ms'] = round(float(elapsed_ms), 2)
    row.update({str(k): _safe(v) for k, v in fields.items()})
    line = json.dumps(row, ensure_ascii=False, separators=(',', ':'))
    with _LOCK:
        with PERF_LOG.open('a', encoding='utf-8') as f:
            f.write(line + '\n')


class Span:
    def __init__(self, stage: str, **fields: Any):
        self.stage = stage
        self.fields = fields
        self.started = 0.0

    def __enter__(self):
        self.started = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        elapsed = (time.perf_counter() - self.started) * 1000
        fields = dict(self.fields)
        fields['ok'] = exc is None
        if exc is not None:
            fields['error'] = str(exc)[:500]
        emit(self.stage, elapsed_ms=elapsed, **fields)
        return False


def recent(limit: int = 50) -> list[dict[str, Any]]:
    try:
        lines = PERF_LOG.read_text(encoding='utf-8').splitlines()[-max(1, limit):]
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        except Exception:
            continue
    return rows
