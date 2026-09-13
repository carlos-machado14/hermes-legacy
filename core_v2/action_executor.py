#!/usr/bin/env python3
from __future__ import annotations
import re, subprocess, time
from typing import Any
from memory_store import remember

ALLOWED_SERVICES = {
    'hermes-local-llm.service',
    'hermes-gateway.service',
    'hermes-fast-router.service',
    'hermes-core-health.service',
}
SAFE_ACTIONS = {'restart_service', 'start_service', 'run_cron'}


def _run(args: list[str], timeout: int = 30) -> dict[str, Any]:
    try:
        p = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
        return {'ok': p.returncode == 0, 'code': p.returncode, 'stdout': (p.stdout or '').strip(), 'stderr': (p.stderr or '').strip()}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _service_action(action: str, service: str) -> dict[str, Any]:
    if service not in ALLOWED_SERVICES:
        return {'ok': False, 'error': 'servico nao permitido'}
    verb = 'restart' if action == 'restart_service' else 'start'
    result = _run(['systemctl', '--user', verb, service], 25)
    time.sleep(2)
    check = _run(['systemctl', '--user', 'is-active', service], 8)
    result['validated_state'] = check.get('stdout') or check.get('stderr')
    result['ok'] = bool(result.get('ok')) and result['validated_state'] == 'active'
    remember('action', f'{verb} {service}', result, result['ok'])
    return result


def _valid_cron_name(name: str) -> bool:
    return bool(name and len(name) <= 120 and re.fullmatch(r"[\w\- &À-ÿ.()]+", name))


def execute(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    if action not in SAFE_ACTIONS:
        return {'ok': False, 'error': 'acao requer aprovacao manual ou nao e permitida'}
    if action in {'restart_service', 'start_service'}:
        return _service_action(action, str(params.get('service', '')))
    if action == 'run_cron':
        name = str(params.get('name', '')).strip()
        if not _valid_cron_name(name):
            return {'ok': False, 'error': 'nome de cron invalido'}
        result = _run(['hermes', 'cron', 'run', name], 30)
        remember('action', f'run cron {name}', result, result.get('ok'))
        return result
    return {'ok': False, 'error': 'acao desconhecida'}
