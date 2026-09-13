#!/usr/bin/env python3
from __future__ import annotations
import json
from typing import Any
from tools import run_tool

READ_ONLY_PLANS: dict[str, list[dict[str, Any]]] = {
    'diagnose_crons': [
        {'tool': 'cron_status'},
        {'tool': 'cron_list'},
        {'tool': 'gateway_logs', 'arguments': {'lines': 35}},
        {'tool': 'llm_logs', 'arguments': {'lines': 25}},
    ],
    'diagnose_services': [
        {'tool': 'services'},
        {'tool': 'gateway_logs', 'arguments': {'lines': 25}},
        {'tool': 'llm_logs', 'arguments': {'lines': 25}},
        {'tool': 'router_logs', 'arguments': {'lines': 25}},
    ],
}


def classify(text: str) -> str | None:
    t = text.lower()
    if 'cron' in t and any(k in t for k in ('falh', 'erro', 'problema', 'nao rod', 'não rod', 'diagnostic', 'verifique')):
        return 'diagnose_crons'
    if any(k in t for k in ('servico', 'serviço', 'gateway', 'llm', 'router')) and any(k in t for k in ('falh', 'erro', 'problema', 'diagnostic', 'verifique')):
        return 'diagnose_services'
    return None


def execute(plan_name: str) -> dict[str, Any]:
    steps = READ_ONLY_PLANS.get(plan_name)
    if not steps:
        return {'ok': False, 'error': f'unknown plan: {plan_name}'}
    results = []
    for step in steps:
        result = run_tool(step['tool'], step.get('arguments'))
        results.append({'step': step, 'result': result})
    return {'ok': True, 'plan': plan_name, 'results': results}


def compact_for_llm(report: dict[str, Any], max_chars: int = 4500) -> str:
    """Keep local-LLM diagnostic prompts small on CPU-only VPSes."""
    text = json.dumps(report, ensure_ascii=False, separators=(',', ':'))
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-(max_chars // 2):]
    return head + '\n...[middle truncated]...\n' + tail
