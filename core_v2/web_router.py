from __future__ import annotations

import re

from site_auditor import audit, format_audit
from web_research import format_research, research, research_company
from web_search_engine import health

URL_RE = re.compile(r'https?://\S+', re.I)


def handle(text: str) -> str | None:
    raw = str(text or '').strip()
    low = raw.casefold()

    if low in {'status web', 'status pesquisa', 'status searxng', 'status navegador'}:
        h = health()
        return f"Pesquisa web local: {'ativa' if h.get('ok') else 'indisponível'}\nSearXNG: {h.get('url')}" + (f"\nErro: {h.get('error')}" if h.get('error') else '')

    if any(k in low for k in ('audite o site', 'auditar site', 'analise o site', 'analisar site')):
        match = URL_RE.search(raw)
        if not match:
            return 'Envie a URL junto. Ex.: audite o site https://empresa.com.br'
        return format_audit(audit(match.group(0)))

    prefixes = ('pesquise na web ', 'pesquisar na web ', 'busque na web ', 'buscar na web ', 'pesquisa web ')
    for prefix in prefixes:
        if low.startswith(prefix):
            query = raw[len(prefix):].strip()
            return format_research(research(query, limit=8))

    if any(k in low for k in ('empresa', 'dentista', 'clínica', 'clinica', 'advogado', 'restaurante', 'loja')) and any(k in low for k in ('colete dados', 'coleta de dados', 'encontre ', 'pesquise ', 'procure ')):
        return format_research(research_company(raw, limit=5))

    return None
