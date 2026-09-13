#!/usr/bin/env python3
from __future__ import annotations
from typing import Any, Callable
from tools import run_tool
from action_executor import execute as execute_action

READ_TOOLS = {
    'system.services': ('services', {}),
    'docker.list': ('docker', {}),
    'cron.status': ('cron_status', {}),
    'cron.list': ('cron_list', {}),
    'logs.gateway': ('gateway_logs', {'lines': 40}),
    'logs.llm': ('llm_logs', {'lines': 40}),
    'logs.router': ('router_logs', {'lines': 40}),
}

ACTION_TOOLS = {
    'system.restart_service': 'restart_service',
    'system.start_service': 'start_service',
    'cron.run': 'run_cron',
}


def list_tools() -> dict[str, Any]:
    return {
        'read': sorted(READ_TOOLS),
        'actions': sorted(ACTION_TOOLS),
        'policy': 'acoes destrutivas/arbitrarias nao sao expostas; somente allowlist segura',
    }


def call(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    if name in READ_TOOLS:
        legacy, defaults = READ_TOOLS[name]
        return run_tool(legacy, {**defaults, **args})
    if name in ACTION_TOOLS:
        return execute_action(ACTION_TOOLS[name], args)
    return {'ok': False, 'error': f'tool nao registrada: {name}'}
