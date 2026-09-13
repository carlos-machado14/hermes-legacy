#!/usr/bin/env python3
from __future__ import annotations

import html, re
from urllib.parse import quote_plus
import httpx
from bs4 import BeautifulSoup


def web_search(query: str, limit: int = 5) -> list[dict[str, str]]:
    query = query.strip()
    if not query: return []
    url = 'https://html.duckduckgo.com/html/?q=' + quote_plus(query)
    headers = {'User-Agent': 'Mozilla/5.0 Hermes-Core/3.0'}
    with httpx.Client(timeout=12, follow_redirects=True, headers=headers) as client:
        r = client.get(url); r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser'); out=[]
    for result in soup.select('.result'):
        a = result.select_one('.result__a')
        if not a: continue
        snippet = result.select_one('.result__snippet')
        out.append({'title': a.get_text(' ', strip=True), 'url': a.get('href',''), 'snippet': snippet.get_text(' ', strip=True) if snippet else ''})
        if len(out) >= max(1, min(limit, 10)): break
    return out


def format_results(query: str, limit: int = 5) -> str:
    try: rows = web_search(query, limit)
    except Exception as exc: return f'Pesquisa externa falhou: {exc}'
    if not rows: return 'Nenhum resultado encontrado.'
    out=[f'Pesquisa: {query}']
    for i,row in enumerate(rows,1):
        out.append(f"{i}. {row['title']}\n{row['snippet']}\n{row['url']}")
    return '\n\n'.join(out)
