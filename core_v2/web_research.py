from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from evidence_store import add as add_evidence
from lead_scoring import score as score_lead
from site_auditor import audit
from site_crawler import crawl
from web_search_engine import search

_SOCIAL_HOSTS = ('instagram.com', 'facebook.com', 'linkedin.com', 'tiktok.com', 'youtube.com')
_DIRECTORY_HOSTS = (
    'wikipedia.org', 'tripadvisor.', 'yelp.', 'solutudo.', 'telelistas.', 'guiamais.', 'apontador.',
    'cylex.', 'kekanto.', 'hagah.', 'reclameaqui.', 'getninjas.', 'habitissimo.', 'jusbrasil.',
    'sebrae.', 'indeed.', 'glassdoor.', 'econodata.', 'cnpj.biz', 'empresasdobrasil.',
)
_GENERIC_PHRASES = (
    'como encontrar clientes', 'como conseguir clientes', 'melhores agências', 'melhores agencias',
    'lista de empresas', 'lista de agências', 'lista de agencias', 'guia de empresas',
    'diretório de empresas', 'diretorio de empresas', 'ranking de', 'vagas de emprego',
    'agências em ', 'agencias em ', 'empresas para trabalhar', 'notícias de ', 'noticias de ',
)


def _remember(query: str, item: dict[str, Any], kind: str = 'search', payload: dict[str, Any] | None = None) -> None:
    try:
        add_evidence(
            query,
            str(item.get('url') or ''),
            str(item.get('title') or ''),
            str(item.get('content') or ''),
            kind,
            payload,
        )
    except Exception:
        pass


def _host(url: str) -> str:
    try:
        return urlparse(str(url or '')).netloc.casefold().removeprefix('www.')
    except Exception:
        return ''


def _is_social(url: str) -> bool:
    host = _host(url)
    return any(domain in host for domain in _SOCIAL_HOSTS)


def _looks_generic(item: dict[str, Any]) -> bool:
    url = str(item.get('url') or '')
    host = _host(url)
    if not host:
        return True
    if any(domain in host for domain in _DIRECTORY_HOSTS):
        return True
    hay = f"{item.get('title') or ''} {item.get('content') or ''}".casefold()
    if any(phrase in hay for phrase in _GENERIC_PHRASES):
        return True
    if any(x in hay for x in ('artigo:', 'blog:', 'guia completo', 'saiba como', 'veja como')) and not _is_social(url):
        return True
    return False


def _entity_name(item: dict[str, Any]) -> str:
    title = re.sub(r'\s+', ' ', str(item.get('title') or '')).strip()
    title = re.sub(
        r'\s*(?:[|\-–—]\s*)?(?:instagram|facebook|linkedin|site oficial|home)\s*$',
        '',
        title,
        flags=re.I,
    ).strip(' |-–—')
    if title:
        return title[:140]
    host = _host(str(item.get('url') or ''))
    return host.split('.', 1)[0].replace('-', ' ').title() if host else 'Empresa'


def _identity(item: dict[str, Any]) -> str:
    name = re.sub(r'\W+', ' ', _entity_name(item).casefold()).strip()
    host = _host(str(item.get('url') or ''))
    if name and len(name) >= 4:
        return name
    return host


def _location_hint(query: str) -> str:
    raw = re.sub(r'\s+', ' ', str(query or '')).strip()
    patterns = (
        r'\bem\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .-]{1,45})\s*,?\s+([A-Z]{2})\b',
        r'\b([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .-]{1,45})\s*,\s*([A-Z]{2})\b',
    )
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            city = re.sub(r'\s+', ' ', match.group(1)).strip(' ,.-')
            state = match.group(2).upper()
            city = re.sub(r'^(?:cliente|empresa|negocio|negócio|site)\s+(?:em\s+)?', '', city, flags=re.I)
            return f'{city} {state}'.strip()
    return ''


def _company_queries(query: str) -> list[str]:
    location = _location_hint(query)
    if not location:
        return [
            query,
            f'{query} telefone instagram',
            f'{query} endereço whatsapp',
            f'{query} site oficial',
        ]
    return [
        f'empresas {location} instagram telefone',
        f'clínica {location} instagram telefone',
        f'restaurante {location} instagram telefone',
        f'loja {location} instagram telefone',
        f'serviços {location} instagram whatsapp',
        f'empresa {location} site oficial contato',
    ]


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


def _enrich_company(query: str, item: dict[str, Any]) -> dict[str, Any]:
    url = str(item.get('url') or '')
    row: dict[str, Any] = {
        'name': _entity_name(item),
        'search': item,
        'sources': [url] if url else [],
        'website': '',
        'crawl': {},
        'audit': {},
    }

    if _is_social(url):
        row['crawl'] = {
            'ok': False,
            'start_url': url,
            'pages': [],
            'contacts': [],
            'socials': [url],
            'images': [],
            'logos': [],
        }
    else:
        row['website'] = url
        try:
            row['crawl'] = crawl(url, max_pages=4)
        except Exception as exc:
            row['crawl'] = {'ok': False, 'contacts': [], 'socials': [], 'images': [], 'logos': [], 'error': str(exc)}
        try:
            row['audit'] = audit(url)
        except Exception as exc:
            row['audit'] = {'ok': False, 'error': str(exc)}

    crawl_data = row.get('crawl') or {}
    for social in crawl_data.get('socials') or []:
        if social not in row['sources']:
            row['sources'].append(social)

    lead = score_lead(row.get('audit'), crawl_data, item)
    value = int(lead.get('score') or 0)
    reasons = list(lead.get('reasons') or [])
    content = f"{item.get('title') or ''} {item.get('content') or ''}".casefold()
    location = _location_hint(query).casefold()
    if location and all(part in content for part in location.split()[:1]):
        value += 5
        reasons.append('sinal de localização compatível')
    if crawl_data.get('socials'):
        value += 4
        reasons.append('presença social pública encontrada')
    if crawl_data.get('contacts'):
        value += 4
        reasons.append('canal de contato público encontrado')
    if _is_social(url) and not row.get('website'):
        value += 8
        reasons.append('presença social sem site oficial verificado')
    value = max(0, min(value, 100))
    row['lead_score'] = {
        'score': value,
        'label': 'quente' if value >= 80 else 'bom' if value >= 65 else 'médio' if value >= 45 else 'baixo',
        'reasons': list(dict.fromkeys(reasons)),
    }
    _remember(query, item, kind='company_candidate', payload={
        'name': row['name'],
        'website': row['website'],
        'lead_score': row['lead_score'],
        'contacts': crawl_data.get('contacts') or [],
        'socials': crawl_data.get('socials') or [],
        'images': crawl_data.get('images') or [],
    })
    return row


def research_company(query: str, limit: int = 5) -> dict[str, Any]:
    raw_candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for variant in _company_queries(query):
        try:
            rows = search(variant, limit=max(6, min(12, int(limit) * 2)))
        except Exception:
            continue
        for item in rows:
            url = str(item.get('url') or '').strip()
            if not url or url in seen_urls or _looks_generic(item):
                continue
            seen_urls.add(url)
            raw_candidates.append(item)
            if len(raw_candidates) >= 24:
                break
        if len(raw_candidates) >= 24:
            break

    companies: list[dict[str, Any]] = []
    seen_entities: set[str] = set()
    for item in raw_candidates:
        identity = _identity(item)
        if not identity or identity in seen_entities:
            continue
        seen_entities.add(identity)
        row = _enrich_company(query, item)
        if not row.get('name') or not str((row.get('search') or {}).get('url') or ''):
            continue
        companies.append(row)

    companies.sort(key=lambda x: int((x.get('lead_score') or {}).get('score', 0)), reverse=True)
    companies = companies[: max(1, min(int(limit), 8))]
    selected = companies[0] if companies else None
    return {
        'ok': bool(companies),
        'query': query,
        'companies': companies,
        'selected': selected,
        'candidates_considered': len(raw_candidates),
    }


def _format_company(report: dict[str, Any]) -> str:
    selected = report.get('selected')
    companies = list(report.get('companies') or [])
    if not isinstance(selected, dict):
        return (
            'Não encontrei um candidato comercial verificável com evidência suficiente ainda. '
            'A pesquisa descartou diretórios, artigos e páginas genéricas em vez de apresentá-los como empresas.'
        )

    score = selected.get('lead_score') or {}
    crawl_data = selected.get('crawl') or {}
    audit_data = selected.get('audit') or {}
    search_item = selected.get('search') or {}
    lines = [
        f"Pesquisa comercial verificada: {report.get('query', '')}",
        '',
        f"Melhor candidato: {selected.get('name') or search_item.get('title') or 'Empresa'}",
        f"Potencial comercial / lead score: {score.get('score', 0)}/100 ({score.get('label', 'n/d')})",
    ]
    if selected.get('website'):
        lines.append(f"Site/página principal: {selected['website']}")
    elif search_item.get('url'):
        lines.append(f"Empresa/página pública: {search_item['url']}")

    reasons = score.get('reasons') or []
    if reasons:
        lines.append('Por que é oportunidade: ' + '; '.join(str(x) for x in reasons[:6]))

    contacts = crawl_data.get('contacts') or []
    socials = crawl_data.get('socials') or []
    images = crawl_data.get('images') or []
    logos = crawl_data.get('logos') or []
    if contacts:
        lines.append('Contatos públicos verificados: ' + ', '.join(str(x) for x in contacts[:8]))
    else:
        lines.append('Contato direto: não verificado nesta etapa.')
    if socials:
        lines.append('Redes sociais: ' + ', '.join(str(x) for x in socials[:8]))
    else:
        lines.append('Redes sociais: não verificadas nesta etapa.')
    if logos:
        lines.append('Logo público: ' + ', '.join(str(x) for x in logos[:3]))
    if images:
        lines.append('Imagens públicas encontradas: ' + ', '.join(str(x) for x in images[:6]))

    if isinstance(audit_data, dict) and audit_data.get('ok'):
        lines.append(f"Auditoria do site: {audit_data.get('score')}/100 ({audit_data.get('grade')})")
        for finding in (audit_data.get('findings') or [])[:5]:
            lines.append(f"- {finding}")

    sources = list(dict.fromkeys(str(x) for x in (selected.get('sources') or []) if x))
    if search_item.get('url') and str(search_item['url']) not in sources:
        sources.insert(0, str(search_item['url']))
    if sources:
        lines.append('Fontes verificadas:')
        lines.extend(f'- {source}' for source in sources[:10])

    if len(companies) > 1:
        lines.append('')
        lines.append('Outros candidatos considerados:')
        for row in companies[1:4]:
            item = row.get('search') or {}
            lead = row.get('lead_score') or {}
            lines.append(f"- {row.get('name') or item.get('title')} — {lead.get('score', 0)}/100 — {item.get('url') or ''}")

    lines.append('')
    lines.append('Diretórios, rankings, agências genéricas e artigos foram filtrados; eles não contam como candidato final.')
    return '\n'.join(lines)


def format_research(report: dict[str, Any]) -> str:
    if 'companies' in report:
        return _format_company(report)

    rows = report.get('results') or []
    if not rows:
        return f"Nenhum resultado encontrado para: {report.get('query', '')}"
    lines = [f"Pesquisa real: {report.get('query', '')}"]
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
    return '\n'.join(lines)
