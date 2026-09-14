from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Callable


@dataclass(frozen=True)
class Capability:
    name: str
    domain: str
    description: str
    risk: str = 'low'
    requires_approval: bool = False
    async_friendly: bool = True


_CAPABILITIES: dict[str, Capability] = {}
_HANDLERS: dict[str, Callable[[dict[str, Any]], Any]] = {}


def register(capability: Capability, handler: Callable[[dict[str, Any]], Any] | None = None) -> None:
    _CAPABILITIES[capability.name] = capability
    if handler is not None:
        _HANDLERS[capability.name] = handler


def get(name: str) -> Capability | None:
    return _CAPABILITIES.get(name)


def handler(name: str) -> Callable[[dict[str, Any]], Any] | None:
    return _HANDLERS.get(name)


def list_capabilities(domain: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for item in _CAPABILITIES.values():
        if domain and item.domain != domain:
            continue
        rows.append(asdict(item))
    return sorted(rows, key=lambda x: (x['domain'], x['name']))


def domains() -> list[str]:
    return sorted({c.domain for c in _CAPABILITIES.values()})


def call(name: str, args: dict[str, Any] | None = None) -> Any:
    capability = get(name)
    if capability is None:
        return {'ok': False, 'error': f'capability_not_found: {name}'}
    fn = handler(name)
    if fn is None:
        return {'ok': False, 'error': f'capability_not_bound: {name}', 'capability': asdict(capability)}
    try:
        return fn(args or {})
    except Exception as exc:
        return {'ok': False, 'error': str(exc), 'capability': name}


def bootstrap() -> None:
    if _CAPABILITIES:
        return

    # Core/general capabilities. Bindings are intentionally lazy so modules remain optional.
    register(Capability('memory.search', 'knowledge', 'Buscar memória relevante no Memory Vault'))
    register(Capability('goals.read', 'personal', 'Consultar objetivos e prioridades'))
    register(Capability('tasks.read', 'personal', 'Consultar tarefas e pendências'))
    register(Capability('web.search', 'research', 'Pesquisar fontes públicas na web'))
    register(Capability('web.crawl', 'research', 'Coletar conteúdo estruturado de páginas públicas'))
    register(Capability('web.audit', 'research', 'Auditar tecnicamente uma página/site'))
    register(Capability('browser.inspect', 'research', 'Renderizar e inspecionar página em navegador headless'))
    register(Capability('github.workspace', 'developer', 'Ler e trabalhar em workspace Git local'))
    register(Capability('system.inspect', 'devops', 'Inspecionar serviços, logs e saúde do host'))
    register(Capability('crm.read', 'business', 'Consultar leads e pipeline comercial'))
    register(Capability('actions.queue', 'control', 'Consultar fila de ações e aprovações'))
    register(Capability('communication.send', 'communication', 'Enviar comunicação externa por integração autorizada', risk='medium', requires_approval=True))
    register(Capability('deploy.production', 'developer', 'Publicar alteração em ambiente de produção', risk='high', requires_approval=True))


bootstrap()
