#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / '.hermes/core-v2/state'
FILE = STATE_DIR / 'proactive_settings.json'

DEFAULTS: dict[str, Any] = {
    'enabled': False,
    'morning_hour': 8,
    'evening_hour': 19,
    'weekly_review_weekday': 6,
    'weekly_review_hour': 18,
    'stall_hours': 24,
    'quiet_start_hour': 22,
    'quiet_end_hour': 7,
}


def load() -> dict[str, Any]:
    data = dict(DEFAULTS)
    try:
        saved = json.loads(FILE.read_text(encoding='utf-8'))
        if isinstance(saved, dict):
            data.update(saved)
    except Exception:
        pass
    return data


def save(**changes: Any) -> dict[str, Any]:
    data = load()
    for key, value in changes.items():
        if key in DEFAULTS and value is not None:
            data[key] = value
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return data


def enable() -> dict[str, Any]:
    return save(enabled=True)


def disable() -> dict[str, Any]:
    return save(enabled=False)


def summary() -> str:
    s = load()
    status = 'ATIVO' if s.get('enabled') else 'PAUSADO'
    return (
        f'Modo proativo: {status}\n'
        f"Brief da manhã: {int(s.get('morning_hour', 8)):02d}:00\n"
        f"Revisão do dia: {int(s.get('evening_hour', 19)):02d}:00\n"
        f"Revisão semanal: domingo {int(s.get('weekly_review_hour', 18)):02d}:00\n"
        f"Alerta de objetivo parado: após {int(s.get('stall_hours', 24))}h sem avanço\n"
        f"Silêncio: {int(s.get('quiet_start_hour', 22)):02d}:00–{int(s.get('quiet_end_hour', 7)):02d}:00"
    )
