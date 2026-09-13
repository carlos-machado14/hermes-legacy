#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from typing import Any

from project_registry import get_project
from incident_store import recent_incidents


def _run(args: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        p = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
        return p.returncode, ((p.stdout or '') + (p.stderr or '')).strip()
    except Exception as exc:
        return 1, repr(exc)


def container_state(name: str) -> dict[str, Any]:
    code, out = _run(['docker', 'inspect', '-f', '{{json .State}}', name], 8)
    if code != 0:
        return {'name': name, 'ok': False, 'error': out[-500:]}
    try:
        state = json.loads(out)
    except Exception:
        state = {'raw': out}
    running = bool(state.get('Running')) if isinstance(state, dict) else False
    return {'name': name, 'ok': running, 'state': state}


def restart_container(name: str) -> dict[str, Any]:
    code, out = _run(['docker', 'restart', name], 25)
    if code != 0:
        return {'name': name, 'ok': False, 'error': out[-500:]}
    state = container_state(name)
    return {'name': name, 'ok': bool(state.get('ok')), 'restart_output': out[-300:], 'state': state}


def project_status(name: str) -> dict[str, Any]:
    project = get_project(name)
    if not project:
        return {'ok': False, 'error': 'project_not_found', 'name': name}
    containers = [container_state(str(x)) for x in (project.get('containers') or []) if str(x).strip()]
    service_states = []
    for service in project.get('services') or []:
        s = str(service).strip()
        if not s:
            continue
        code, out = _run(['systemctl', '--user', 'is-active', s], 5)
        service_states.append({'name': s, 'ok': code == 0 and out.strip() == 'active', 'state': out.strip() or 'unknown'})
    incidents = [i for i in recent_incidents(100) if str((i.get('details') or {}).get('project', '')).casefold() == name.casefold()]
    ok = all(x.get('ok') for x in containers + service_states) if (containers or service_states) else True
    return {'ok': ok, 'project': project, 'containers': containers, 'services': service_states, 'recent_incidents': incidents[-10:]}


def restart_project(name: str) -> dict[str, Any]:
    project = get_project(name)
    if not project:
        return {'ok': False, 'error': 'project_not_found', 'name': name}
    results: list[dict[str, Any]] = []
    for service in project.get('services') or []:
        s = str(service).strip()
        if s:
            code, out = _run(['systemctl', '--user', 'restart', s], 20)
            results.append({'type': 'service', 'name': s, 'ok': code == 0, 'detail': out[-300:]})
    for container in project.get('containers') or []:
        c = str(container).strip()
        if c:
            r = restart_container(c)
            r['type'] = 'container'
            results.append(r)
    return {'ok': all(r.get('ok') for r in results) if results else False, 'project': name, 'results': results, 'note': 'Nenhum alvo configurado.' if not results else None}
