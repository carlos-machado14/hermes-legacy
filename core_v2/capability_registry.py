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
    execution: str = 'local'  # local | freud


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
    if capability.execution == 'freud':
        return {
            'ok': False,
            'error': 'capability_requires_freud_tool_broker',
            'capability': asdict(capability),
            'hint': 'Esta capacidade deve ser executada pelo Freud no contexto autenticado do usuário; credenciais nunca ficam no Hermes.',
        }
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

    # Capacidades locais do Core.
    register(Capability('memory.search', 'knowledge', 'Buscar memória relevante no Memory Vault'))
    register(Capability('goals.read', 'personal', 'Consultar objetivos e prioridades'))
    register(Capability('tasks.read', 'personal', 'Consultar tarefas e pendências'))
    register(Capability('web.search', 'research', 'Pesquisar fontes públicas na web'))
    register(Capability('web.crawl', 'research', 'Coletar conteúdo estruturado de páginas públicas'))
    register(Capability('web.audit', 'research', 'Auditar tecnicamente uma página/site'))
    register(Capability('browser.inspect', 'research', 'Renderizar e inspecionar página em navegador headless'))
    register(Capability('github.workspace', 'developer', 'Ler e trabalhar em workspace Git local do administrador'))
    register(Capability('system.inspect', 'devops', 'Inspecionar serviços, logs e saúde do host'))
    register(Capability('crm.read', 'business', 'Consultar CRM local quando configurado'))
    register(Capability('actions.queue', 'control', 'Consultar fila local de ações e aprovações'))

    # Capacidades conectadas pertencem ao Control Plane Freud. O Core conhece a intenção,
    # mas nunca recebe nem persiste as credenciais do usuário.
    register(Capability('connected.status', 'personal', 'Consultar integrações conectadas do usuário autenticado no Freud', execution='freud'))
    register(Capability('assistant.overview', 'personal', 'Cruzar agenda, inbox e projetos conectados para montar panorama do usuário', execution='freud'))
    register(Capability('calendar.read', 'personal', 'Consultar Google Calendar conectado do usuário', execution='freud'))
    register(Capability('calendar.create', 'personal', 'Criar evento no calendário conectado', risk='medium', requires_approval=True, execution='freud'))
    register(Capability('email.read', 'communication', 'Pesquisar Gmail conectado do usuário', execution='freud'))
    register(Capability('email.send', 'communication', 'Enviar e-mail por integração autorizada', risk='medium', requires_approval=True, execution='freud'))
    register(Capability('github.remote.read', 'developer', 'Consultar repositórios e issues via conta GitHub conectada do usuário', execution='freud'))
    register(Capability('github.remote.write', 'developer', 'Alterar recursos remotos do GitHub via Freud', risk='medium', requires_approval=True, execution='freud'))
    register(Capability('whatsapp.send', 'communication', 'Enviar WhatsApp pela integração do usuário', risk='medium', requires_approval=True, execution='freud'))
    register(Capability('deploy.production', 'developer', 'Publicar alteração em ambiente de produção', risk='high', requires_approval=True, execution='freud'))


bootstrap()
