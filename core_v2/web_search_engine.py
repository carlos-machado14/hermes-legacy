from __future__ import annotations

import os
from typing import Any

import httpx

SEARXNG_URL = os.getenv('HERMES_SEARXNG_URL', 'http://127.0.0.1:8087').rstrip('/')


def health() -> dict[str, Any]:
    try:
        r = httpx.get(f'{SEARXNG_URL}/healthz', timeout=5.0)
        if r.status_code < 400:
            return {'ok': True, 'url': SEARXNG_URL}
    except Exception:
        pass
    try:
        r = httpx.get(SEARXNG_URL, timeout=5.0)
        return {'ok': r.status_code < 500, 'url': SEARXNG_URL, 'status_code': r.status_code}
    except Exception as exc:
        return {'ok': False, 'url': SEARXNG_URL, 'error': str(exc)}


def search(query: str, limit: int = 8, language: str = 'pt-BR') -> list[dict[str, Any]]:
    q = str(query or '').strip()
    if not q:
        return []
    params = {
        'q': q,
        'format': 'json',
        'language': language,
        'safesearch': 1,
        'categories': 'general',
    }
    with httpx.Client(timeout=20.0, follow_redirects=True, headers={'User-Agent': 'HermesLocal/4.1'}) as client:
        r = client.get(f'{SEARXNG_URL}/search', params=params)
        r.raise_for_status()
        payload = r.json()
    out: list[dict[str, Any]] = []
    for item in list(payload.get('results') or [])[: max(1, min(int(limit), 20))]:
        if not isinstance(item, dict):
            continue
        url = str(item.get('url') or '').strip()
        if not url:
            continue
        out.append({
            'title': str(item.get('title') or '').strip(),
            'url': url,
            'content': str(item.get('content') or '').strip(),
            'engine': str(item.get('engine') or '').strip(),
            'score': item.get('score'),
        })
    return out


def format_results(items: list[dict[str, Any]]) -> str:
    if not items:
        return 'Nenhum resultado encontrado.'
    lines = []
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item.get('title') or item.get('url')}\n{item.get('url')}\n{item.get('content') or ''}".strip())
    return '\n\n'.join(lines)
