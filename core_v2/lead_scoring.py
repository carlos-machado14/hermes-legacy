from __future__ import annotations

from typing import Any


def score(audit: dict[str, Any] | None, crawl: dict[str, Any] | None, search_item: dict[str, Any] | None = None) -> dict[str, Any]:
    audit = audit or {}
    crawl = crawl or {}
    search_item = search_item or {}
    value = 50
    reasons: list[str] = []

    site_score = audit.get('score')
    if isinstance(site_score, (int, float)):
        if site_score < 40:
            value += 25; reasons.append('site muito fraco')
        elif site_score < 60:
            value += 18; reasons.append('site abaixo do ideal')
        elif site_score < 75:
            value += 10; reasons.append('site com espaço claro para melhoria')
        elif site_score >= 90:
            value -= 15; reasons.append('site já está forte')

    contacts = crawl.get('contacts') or []
    socials = crawl.get('socials') or []
    if contacts:
        value += 12; reasons.append('contato direto encontrado')
    if socials:
        value += 6; reasons.append('redes sociais encontradas')
    if crawl.get('ok') is False:
        value += 12; reasons.append('site ausente ou indisponível')

    content = str(search_item.get('content') or '').casefold()
    if any(k in content for k in ('whatsapp', 'telefone', 'instagram')):
        value += 5; reasons.append('sinais de contato na busca')

    value = max(0, min(int(value), 100))
    label = 'quente' if value >= 80 else 'bom' if value >= 65 else 'médio' if value >= 45 else 'baixo'
    return {'score': value, 'label': label, 'reasons': reasons}
