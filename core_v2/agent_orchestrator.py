from __future__ import annotations

from typing import Any

from agent_catalog import list_agents
from domain_router import classify


def select_agents(text: str) -> list[dict[str, Any]]:
    route = classify(text)
    wanted = [route.get('primary_domain'), *(route.get('secondary_domains') or [])]
    agents = list_agents()
    out: list[dict[str, Any]] = []
    for domain in wanted:
        for name, spec in agents.items():
            if str(spec.get('domain') or '') == str(domain):
                out.append({'name': name, **spec})
                break
    if not out:
        for name, spec in agents.items():
            if str(spec.get('domain') or '') == 'control':
                out.append({'name': name, **spec})
                break
    return out[:4]


def context_for_step(step: dict[str, Any], request: str) -> str:
    domain = str(step.get('domain') or '').strip()
    agents = list_agents()
    chosen = None
    for name, spec in agents.items():
        if str(spec.get('domain') or '') == domain:
            chosen = {'name': name, **spec}
            break
    if not chosen:
        selected = select_agents(request)
        chosen = selected[0] if selected else {'name': 'Hermes General', 'role': 'Assistente geral'}
    return (
        f"ESPECIALISTA INTERNO: {chosen.get('name')}\n"
        f"PAPEL: {chosen.get('role') or chosen.get('description') or 'Executar a etapa com precisão.'}\n"
        f"DOMÍNIO: {domain or chosen.get('domain') or 'general'}"
    )
