#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / '.hermes/core-v2/state'
FILE = STATE_DIR / 'autonomy_settings.json'

DEFAULTS: dict[str, Any] = {
    'enabled': False,
    'max_actions_per_cycle': 2,
    'auto_execute_low_risk': True,
    'require_approval_medium': True,
    'require_approval_high': True,
    'cycle_minutes': 30,
}


def load() -> dict[str, Any]:
    data = dict(DEFAULTS)
    try:
        saved = json.loads(FILE.read_text(encoding='utf-8'))
        if isinstance(saved, dict): data.update(saved)
    except Exception:
        pass
    return data


def save(**changes: Any) -> dict[str, Any]:
    data = load()
    for key, value in changes.items():
        if key in DEFAULTS and value is not None: data[key] = value
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return data


def enable() -> dict[str, Any]: return save(enabled=True)
def disable() -> dict[str, Any]: return save(enabled=False)


def summary() -> str:
    s = load(); status = 'ATIVA' if s.get('enabled') else 'PAUSADA'
    return (
        f'Execução autônoma: {status}\n'
        f"Ações por ciclo: {int(s.get('max_actions_per_cycle',2))}\n"
        f"Baixo risco automático: {'sim' if s.get('auto_execute_low_risk') else 'não'}\n"
        f"Médio/alto risco: exigem aprovação\n"
        f"Ciclo: a cada {int(s.get('cycle_minutes',30))} min"
    )
