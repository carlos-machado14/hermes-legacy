#!/usr/bin/env python3
from __future__ import annotations
import json
import shutil
import subprocess
from typing import Any


def _run(args: list[str], timeout: int = 15) -> dict[str, Any]:
    p = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    return {
        'ok': p.returncode == 0,
        'code': p.returncode,
        'stdout': (p.stdout or '').strip(),
        'stderr': (p.stderr or '').strip(),
    }


def service_status() -> dict[str, str]:
    names = [
        'hermes-local-llm.service',
        'hermes-gateway.service',
        'hermes-fast-router.service',
    ]
    out: dict[str, str] = {}
    for name in names:
        r = _run(['systemctl', '--user', 'is-active', name], timeout=8)
        out[name] = r['stdout'] or r['stderr'] or 'unknown'
    return out


def docker_status() -> dict[str, Any]:
    if not shutil.which('docker'):
        return {'available': False, 'containers': []}
    r = _run(['docker', 'ps', '--format', '{{.Names}}|{{.Status}}|{{.Image}}'], timeout=12)
    containers = []
    if r['ok']:
        for line in r['stdout'].splitlines():
            if not line.strip():
                continue
            parts = line.split('|', 2)
            containers.append({
                'name': parts[0] if len(parts) > 0 else '',
                'status': parts[1] if len(parts) > 1 else '',
                'image': parts[2] if len(parts) > 2 else '',
            })
    return {'available': True, 'ok': r['ok'], 'containers': containers, 'error': r['stderr']}


def cron_status() -> dict[str, Any]:
    if not shutil.which('hermes'):
        return {'available': False}
    r = _run(['hermes', 'cron', 'status'], timeout=15)
    return {'available': True, 'ok': r['ok'], 'output': r['stdout'], 'error': r['stderr']}


def cron_list() -> dict[str, Any]:
    if not shutil.which('hermes'):
        return {'available': False}
    r = _run(['hermes', 'cron', 'list'], timeout=20)
    return {'available': True, 'ok': r['ok'], 'output': r['stdout'], 'error': r['stderr']}


def journal_tail(service: str, lines: int = 40) -> dict[str, Any]:
    allowed = {
        'hermes-local-llm.service',
        'hermes-gateway.service',
        'hermes-fast-router.service',
    }
    if service not in allowed:
        return {'ok': False, 'error': 'service not allowed'}
    r = _run(['journalctl', '--user', '-u', service, '-n', str(lines), '--no-pager', '-l'], timeout=12)
    return {'ok': r['ok'], 'output': r['stdout'], 'error': r['stderr']}


def run_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    arguments = arguments or {}
    tools = {
        'services': lambda: service_status(),
        'docker': lambda: docker_status(),
        'cron_status': lambda: cron_status(),
        'cron_list': lambda: cron_list(),
        'gateway_logs': lambda: journal_tail('hermes-gateway.service', int(arguments.get('lines', 40))),
        'llm_logs': lambda: journal_tail('hermes-local-llm.service', int(arguments.get('lines', 40))),
        'router_logs': lambda: journal_tail('hermes-fast-router.service', int(arguments.get('lines', 40))),
    }
    if name not in tools:
        return {'ok': False, 'error': f'unknown tool: {name}'}
    try:
        result = tools[name]()
        return {'ok': True, 'tool': name, 'result': result}
    except Exception as e:
        return {'ok': False, 'tool': name, 'error': str(e)}


def pretty(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)
