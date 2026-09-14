from __future__ import annotations

from typing import Any

from evidence_store import add as add_evidence
from lead_scoring import score as score_lead
from site_auditor import audit
from site_crawler import crawl
from web_search_engine import search


def _remember(query: str, item: dict[str, Any], kind: str = 'search', payload: dict[str, Any] | None = None) -> None:
    try:
        add_evidence(query, str(item.get('url') or ''), str(item.get('title') or ''), str(item.get('content') or ''), kind, payload)
    except Exception:
        pass


def research(query: str, limit: int = 6, audit_sites: bool = False) -> dict[str, Any]:
    results = search(query, limit=limit)
    enriched: list[dict[str, Any]] = []
    for item in results:
        row = dict(item)
        if audit_sites:
            row['audit'] = audit(item.get('url') or '')
        _remember(query, item, payload={'audit': row.get('audit')})
        enriched.append(row)
    return {'ok': True, 'query': query, 'results': enriched}


def deep_research(query: str, limit_per_query: int = 5) -> dict[str, Any]:
    variants = [query, f'{query} contato', f'{query} site oficial']
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for variant in variants:
        for item in search(variant, limit=limit_per_query):
            url = str(item.get('url') or '')
            if not url or url in seen:
                continue
            seen.add(url)
            _remember(query, item, kind='deep_search')
            results.append(item)
            if len(results) >= 15:
                break
    return {'ok': True, 'query': query, 'results': results, 'sources': len(results)}


def research_company(query: str, limit: int = 5) -> dict[str, Any]:
    results = search(query, limit=limit)
    companies: list[dict[str, Any]] = []
    for item in results:
        url = str(item.get('url') or '')
        row: dict[str, Any] = {'search': item}
        if url:
            row['crawl'] = crawl(url, max_pages=3)
            row['audit'] = audit(url)
            row['lead_score'] = score_lead(row['audit'], row['crawl'], item)
            _remember(query, item, kind='company', payload={'audit': row['audit'], 'lead_score': row['lead_score']})
        companies.append(row)
    companies.sort(key=lambda x: int((x.get('lead_score') or {}).get('score', 0)), reverse=True)
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
        lead_score = row.get('lead_score') if isinstance(row, dict) else None
        if isinstance(lead_score, dict):
            lines.append(f"Lead score: {lead_score.get('score')}/100 ({lead_score.get('label')})")
            if lead_score.get('reasons'):
                lines.append('Motivos: ' + ', '.join(lead_score.get('reasons')[:5]))
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
