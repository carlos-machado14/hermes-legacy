from __future__ import annotations

from typing import Any

from universal_planner import build as build_universal


def _tool_for(step: dict[str, Any]) -> str:
    domain = str(step.get('domain') or '').casefold()
    instruction = str(step.get('instruction') or '').casefold()
    if domain == 'research':
        if any(k in instruction for k in ('auditar site','audite o site','auditoria do site')):
            return 'site_audit'
        if any(k in instruction for k in ('coletar páginas','coletar paginas','crawler','contatos do site')):
            return 'site_crawl'
        return 'web_research'
    return 'llm'


def build_plan(request: str) -> list[dict[str, Any]]:
    """Compatibility adapter for the durable runtime.

    The Universal Planner now decides domains and specialist roles. The durable
    executor still consumes the compact step format and deterministic web tools
    where useful.
    """
    plan = build_universal(request)
    clean: list[dict[str, Any]] = []
    for item in (plan.get('steps') or [])[:8]:
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or '').strip()
        instruction = str(item.get('instruction') or '').strip()
        if not title or not instruction:
            continue
        step = {
            'title': title[:160],
            'instruction': instruction[:3000],
            'validator': str(item.get('validator') or 'quality'),
            'domain': str(item.get('domain') or plan.get('route', {}).get('primary_domain') or 'personal'),
            'requires_approval': bool(item.get('requires_approval', False)),
        }
        step['tool'] = _tool_for(step)
        clean.append(step)
    if not clean:
        clean = [
            {
                'title': 'Executar a solicitação',
                'instruction': f'Execute integralmente esta solicitação: {request}',
                'validator': 'quality',
                'domain': 'personal',
                'requires_approval': False,
                'tool': 'llm',
            },
            {
                'title': 'Validar resultado final',
                'instruction': 'Confira se a solicitação original foi realmente concluída e corrija lacunas.',
                'validator': 'final',
                'domain': 'control',
                'requires_approval': False,
                'tool': 'llm',
            },
        ]
    return clean
