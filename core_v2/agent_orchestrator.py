from __future__ import annotations

from typing import Any

from agent_catalog import list_agents
from domain_router import classify


def _matches(spec: dict[str, Any], domain: str) -> bool:
    return domain in [str(x) for x in (spec.get('domains') or [])]


def select_agents(text: str) -> list[dict[str, Any]]:
    route = classify(text)
    wanted = [route.get('primary_domain'), *(route.get('secondary_domains') or [])]
    agents = list_agents()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for domain in [str(x) for x in wanted if x]:
        for name, spec in agents.items():
            if name in seen:
                continue
            if _matches(spec, domain):
                out.append({'name': name, **spec})
                seen.add(name)
                break
    if not out and 'general' in agents:
        out.append({'name': 'general', **agents['general']})
    if 'reviewer' in agents and 'reviewer' not in seen:
        out.append({'name': 'reviewer', **agents['reviewer']})
    return out[:4]


def context_for_step(step: dict[str, Any], request: str) -> str:
    domain = str(step.get('domain') or '').strip()
    agents = list_agents()
    chosen: dict[str, Any] | None = None
    for name, spec in agents.items():
        if domain and _matches(spec, domain):
            chosen = {'name': name, **spec}
            break
    if not chosen:
        selected = select_agents(request)
        chosen = selected[0] if selected else {'name': 'general', 'title': 'General Assistant', 'purpose': 'Assistente geral.'}
    return (
        f"ESPECIALISTA INTERNO: {chosen.get('title') or chosen.get('name')}\n"
        f"PAPEL: {chosen.get('purpose') or 'Executar a etapa com precisão.'}\n"
        f"DOMÍNIO: {domain or 'general'}"
    )
