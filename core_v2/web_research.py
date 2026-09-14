from __future__ import annotations

from typing import Any

from site_auditor import audit
from site_crawler import crawl
from web_search_engine import search


def research(query: str, limit: int = 6, audit_sites: bool = False) -> dict[str, Any]:
    results = search(query, limit=limit)
    enriched: list[dict[str, Any]] = []
    for item in results:
        row = dict(item)
        if audit_sites:
            row['audit'] = audit(item.get('url') or '')
        enriched.append(row)
    return {'ok': True, 'query': query, 'results': enriched}


def research_company(query: str, limit: int = 5) -> dict[str, Any]:
    results = search(query, limit=limit)
    companies: list[dict[str, Any]] = []
    for item in results:
        url = str(item.get('url') or '')
        row: dict[str, Any] = {'search': item}
        if url:
            row['crawl'] = crawl(url, max_pages=3)
            row['audit'] = audit(url)
        companies.append(row)
    return {'ok': True, 'query': query, 'companies': companies}


def format_research(report: dict[str, Any]) -> str:
    rows = report.get('results') or report.get('companies') or []
    if not rows:
        return f"Nenhum resultado encontrado para: {report.get('query','')}"
    lines = [f"Pesquisa real: {report.get('query','')}"]
    for i, row in enumerate(rows, 1):
        item = row.get('search') if isinstance(row, dict) and 'search' in row else row
        title = item.get('title') or item.get('url') or f'Resultado {i}'
        url = item.get('url') or ''
        lines.append(f"\n{i}. {title}\n{url}")
        if item.get('content'):
            lines.append(str(item.get('content'))[:500])
        audit_data = row.get('audit') if isinstance(row, dict) else None
        if isinstance(audit_data, dict) and audit_data.get('ok'):
            lines.append(f"Auditoria: {audit_data.get('score')}/100 ({audit_data.get('grade')})")
            for finding in (audit_data.get('findings') or [])[:5]:
                lines.append(f"- {finding}")
        crawl_data = row.get('crawl') if isinstance(row, dict) else None
        if isinstance(crawl_data, dict):
            contacts = crawl_data.get('contacts') or []
            socials = crawl_data.get('socials') or []
            if contacts:
                lines.append('Contatos encontrados: ' + ', '.join(contacts[:5]))
            if socials:
                lines.append('Redes encontradas: ' + ', '.join(socials[:5]))
    return '\n'.join(lines)
