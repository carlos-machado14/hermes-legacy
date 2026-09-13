#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, time
from pathlib import Path
from typing import Any
from action_executor import execute
from memory_store import remember, recent

SERVICES = [
    'hermes-local-llm.service',
    'hermes-gateway.service',
    'hermes-fast-router.service',
    'hermes-core-health.service',
]
STATE = Path.home() / '.hermes/core-v2/state/recovery.json'
COOLDOWN = 300


def _run(args: list[str], timeout: int = 10) -> tuple[int, str]:
    p = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    return p.returncode, ((p.stdout or '') + (p.stderr or '')).strip()


def _active(service: str) -> bool:
    code, out = _run(['systemctl', '--user', 'is-active', service], 6)
    return code == 0 and out.strip() == 'active'


def _load() -> dict[str, Any]:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {'last_attempt': {}}


def _save(data: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(data, indent=2), encoding='utf-8')


def recover_once() -> dict[str, Any]:
    state = _load()
    last = state.setdefault('last_attempt', {})
    now = int(time.time())
    report: dict[str, Any] = {'checked': {}, 'actions': []}
    for service in SERVICES:
        ok = _active(service)
        report['checked'][service] = 'active' if ok else 'inactive'
        if ok:
            continue
        if now - int(last.get(service, 0)) < COOLDOWN:
            report['actions'].append({'service': service, 'action': 'cooldown'})
            continue
        last[service] = now
        result = execute('restart_service', {'service': service})
        report['actions'].append({'service': service, 'action': 'restart', 'result': result})
        remember('recovery', f'auto recovery {service}', result, result.get('ok'))
    state['last_run'] = now
    _save(state)
    report['ok'] = all(v == 'active' for v in report['checked'].values()) or all(a.get('result', {}).get('ok', True) for a in report['actions'])
    return report


def history(limit: int = 20) -> list[dict[str, Any]]:
    return recent(limit=limit, kind='recovery')


if __name__ == '__main__':
    print(json.dumps(recover_once(), ensure_ascii=False, indent=2))
