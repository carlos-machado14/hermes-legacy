from __future__ import annotations

from agent_catalog import list_agents
from capability_registry import domains, list_capabilities
from domain_router import classify
from universal_planner import build


def _capability_summary() -> str:
    grouped: dict[str, list[str]] = {}
    for item in list_capabilities():
        grouped.setdefault(item['domain'], []).append(item['name'])
    lines = ['Hermes v4.2 — Universal Agent Runtime', '', 'Domínios/capacidades:']
    for domain in sorted(grouped):
        lines.append(f"- {domain}: {', '.join(grouped[domain])}")
    lines.append('')
    lines.append('Agentes especialistas: ' + ', '.join(sorted(list_agents())))
    lines.append('O Hermes continua sendo uma única inteligência; especialistas são papéis internos coordenados pelo mesmo contexto/memória.')
    return '\n'.join(lines)


def handle(text: str) -> str | None:
    raw = text.strip()
    low = raw.casefold()
    if low in {'status universal','status do agente','status hermes','capacidades','minhas capacidades','o que voce sabe fazer','o que você sabe fazer'}:
        return _capability_summary()
    if low in {'agentes','meus agentes','agentes disponiveis','agentes disponíveis'}:
        lines = ['Agentes internos do Hermes:']
        for name, spec in list_agents().items():
            lines.append(f"- {name}: {spec['purpose']}")
        return '\n'.join(lines)
    if low.startswith('roteie ') or low.startswith('rotear '):
        body = raw.split(' ', 1)[1].strip()
        route = classify(body)
        return f"Domínio principal: {route['primary_domain']}\nAgente: {route['agent']}\nSecundários: {', '.join(route['secondary_domains']) or 'nenhum'}"
    if low.startswith('planeje universal ') or low.startswith('plano universal '):
        body = raw.split(' ', 2)[2].strip()
        plan = build(body)
        lines = [f"Rota: {plan['route'].get('primary_domain','geral')} / {plan['route'].get('agent','general')}", 'Definition of Done:']
        for item in plan.get('definition_of_done') or []:
            lines.append(f'- {item}')
        lines.append('Plano:')
        for i, step in enumerate(plan.get('steps') or [], 1):
            lines.append(f"{i}. [{step.get('domain')}] {step.get('title')}")
        return '\n'.join(lines)
    return None
