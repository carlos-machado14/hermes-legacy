#!/usr/bin/env python3
from __future__ import annotations

import re
from urllib.parse import urlparse

from project_registry import list_projects, upsert_project, remove_project, get_project
from project_ops import project_status, restart_project

URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)
REPO_RE = re.compile(r'\b([\w.-]+/[\w.-]+)\b')


def _clean_name(value: str) -> str:
    return re.sub(r'\s+', ' ', value.strip(' .,:;-'))


def _fmt_projects() -> str:
    projects = list_projects()
    if not projects:
        return 'Nenhum projeto cadastrado ainda.'
    lines = ['Projetos cadastrados:']
    for p in projects:
        extra = []
        if p.get('repo'):
            extra.append(f"repo={p['repo']}")
        if p.get('health_url'):
            extra.append(f"health={p['health_url']}")
        if p.get('containers'):
            extra.append(f"containers={','.join(map(str, p['containers']))}")
        if p.get('services'):
            extra.append(f"services={','.join(map(str, p['services']))}")
        lines.append(f"- {p.get('name')}" + (f" ({' | '.join(extra)})" if extra else ''))
    return '\n'.join(lines)


def _format_status(report: dict) -> str:
    if report.get('error') == 'project_not_found':
        return f"Projeto '{report.get('name')}' nao encontrado."
    p = report.get('project') or {}
    lines = [f"Projeto {p.get('name')}: {'OK' if report.get('ok') else 'ATENCAO'}"]
    if p.get('repo'):
        lines.append(f"Repo: {p['repo']}")
    if p.get('health_url'):
        lines.append(f"Health: {p['health_url']}")
    for s in report.get('services') or []:
        lines.append(f"Servico {s.get('name')}: {s.get('state')}")
    for c in report.get('containers') or []:
        state = (c.get('state') or {}).get('Status') if isinstance(c.get('state'), dict) else None
        lines.append(f"Container {c.get('name')}: {'running' if c.get('ok') else (state or 'falha')}")
    incidents = report.get('recent_incidents') or []
    if incidents:
        lines.append(f"Incidentes recentes: {len(incidents)}")
    return '\n'.join(lines)


def _parse_csv_after(text: str, keys: tuple[str, ...]) -> list[str]:
    lower = text.lower()
    for key in keys:
        idx = lower.find(key)
        if idx >= 0:
            raw = text[idx + len(key):]
            raw = re.split(r'\b(?:repo|health|url|servi[cç]os?|containers?)\b\s*[:=]?', raw, maxsplit=1, flags=re.IGNORECASE)[0]
            return [x.strip() for x in re.split(r'[,;]', raw) if x.strip()]
    return []


def handle(text: str) -> str | None:
    original = text.strip()
    t = original.lower().strip()

    if any(x in t for x in ('quais projetos', 'listar projetos', 'liste os projetos', 'meus projetos')):
        return _fmt_projects()

    m = re.search(r'(?:status|como est[aá])\s+(?:do\s+)?projeto\s+(.+)$', original, re.IGNORECASE)
    if m:
        return _format_status(project_status(_clean_name(m.group(1))))

    m = re.search(r'(?:reinicie|reiniciar)\s+(?:o\s+)?projeto\s+(.+)$', original, re.IGNORECASE)
    if m:
        name = _clean_name(m.group(1))
        report = restart_project(name)
        if report.get('error') == 'project_not_found':
            return f"Projeto '{name}' nao encontrado."
        if report.get('note'):
            return f"Projeto '{name}' existe, mas nao possui servicos ou containers configurados para reinicio."
        oks = sum(1 for x in report.get('results', []) if x.get('ok'))
        total = len(report.get('results', []))
        return f"Reinicio do projeto {name}: {oks}/{total} alvos OK."

    m = re.search(r'(?:remova|remover|apague|apagar)\s+(?:o\s+)?projeto\s+(.+)$', original, re.IGNORECASE)
    if m:
        name = _clean_name(m.group(1))
        return f"Projeto '{name}' removido." if remove_project(name) else f"Projeto '{name}' nao encontrado."

    if re.search(r'\b(?:cadastre|cadastrar|adicione|adicionar|registre|registrar)\b.*\bprojeto\b', t):
        name_match = re.search(r'projeto\s+["\']?([^"\']+?)["\']?(?:\s+(?:com|repo|health|url|servi[cç]o|container)|$)', original, re.IGNORECASE)
        if not name_match:
            return 'Informe o nome do projeto. Ex.: cadastre projeto Meu App com health https://site/health'
        name = _clean_name(name_match.group(1))
        project = {'name': name, 'enabled': True}
        urls = URL_RE.findall(original)
        if urls:
            project['health_url'] = urls[0].rstrip('.,;)')
        repo_match = re.search(r'\brepo\s*[:=]?\s*([\w.-]+/[\w.-]+)', original, re.IGNORECASE)
        if repo_match:
            project['repo'] = repo_match.group(1)
        containers = _parse_csv_after(original, ('containers:', 'container:', 'containers ', 'container '))
        services = _parse_csv_after(original, ('servicos:', 'serviços:', 'servico:', 'serviço:', 'servicos ', 'serviços '))
        if containers:
            project['containers'] = containers
        if services:
            project['services'] = services
        saved = upsert_project(project)
        details = []
        for key in ('repo', 'health_url'):
            if saved.get(key):
                details.append(f"{key}={saved[key]}")
        if saved.get('containers'):
            details.append(f"containers={','.join(saved['containers'])}")
        if saved.get('services'):
            details.append(f"services={','.join(saved['services'])}")
        return f"Projeto '{name}' cadastrado." + ("\n" + " | ".join(details) if details else '')

    m = re.search(r'(?:monitore|monitorar)\s+(?:o\s+)?projeto\s+(.+?)\s+(?:em|no|na|url|health)\s+(https?://\S+)', original, re.IGNORECASE)
    if m:
        name = _clean_name(m.group(1))
        url = m.group(2).rstrip('.,;)')
        current = get_project(name) or {'name': name}
        current['health_url'] = url
        current['enabled'] = True
        upsert_project(current)
        return f"Monitoramento configurado para '{name}' em {url}."

    return None
