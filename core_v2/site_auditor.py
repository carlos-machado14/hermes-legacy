from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from browser_tools import inspect_page

USER_AGENT = 'HermesLocal/4.1 (+local site audit)'


def _normalize(url: str) -> str:
    raw = str(url or '').strip()
    if not raw.startswith(('http://', 'https://')):
        raw = 'https://' + raw
    return raw


def audit(url: str) -> dict[str, Any]:
    target = _normalize(url)
    findings: list[str] = []
    score = 100
    metrics: dict[str, Any] = {'url': target}

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True, headers={'User-Agent': USER_AGENT}) as client:
            r = client.get(target)
            metrics['status'] = r.status_code
            metrics['final_url'] = str(r.url)
            metrics['https'] = str(r.url).startswith('https://')
            metrics['bytes'] = len(r.content)
            metrics['server'] = r.headers.get('server', '')
            metrics['cache_control'] = r.headers.get('cache-control', '')
            if r.status_code >= 400:
                findings.append(f'HTTP {r.status_code}: site indisponível ou com erro.')
                score -= 45
            if not metrics['https']:
                findings.append('Site sem HTTPS.')
                score -= 15

            soup = BeautifulSoup(r.text, 'html.parser')
            title = soup.title.get_text(' ', strip=True) if soup.title else ''
            metrics['title'] = title
            if not title:
                findings.append('Título HTML ausente.')
                score -= 8
            desc = soup.find('meta', attrs={'name': re.compile('description', re.I)})
            metrics['meta_description'] = desc.get('content', '').strip() if desc else ''
            if not metrics['meta_description']:
                findings.append('Meta description ausente.')
                score -= 7
            viewport = soup.find('meta', attrs={'name': re.compile('viewport', re.I)})
            metrics['viewport'] = bool(viewport)
            if not viewport:
                findings.append('Viewport mobile ausente; possível problema de responsividade.')
                score -= 15
            h1s = soup.find_all('h1')
            metrics['h1_count'] = len(h1s)
            if len(h1s) == 0:
                findings.append('Nenhum H1 encontrado.')
                score -= 6
            elif len(h1s) > 2:
                findings.append('Múltiplos H1; estrutura semântica pode estar confusa.')
                score -= 3
            text = soup.get_text(' ', strip=True)
            metrics['text_chars'] = len(text)
            if len(text) < 500:
                findings.append('Pouco conteúdo textual; pode prejudicar SEO e conversão.')
                score -= 8
            links = [str(a.get('href') or '') for a in soup.find_all('a', href=True)]
            metrics['whatsapp'] = any('wa.me/' in x or 'api.whatsapp.com' in x for x in links)
            metrics['phone'] = any(x.startswith('tel:') for x in links)
            metrics['email'] = any(x.startswith('mailto:') for x in links)
            if not (metrics['whatsapp'] or metrics['phone'] or metrics['email']):
                findings.append('Nenhum CTA de contato direto detectado.')
                score -= 10
            metrics['images'] = len(soup.find_all('img'))
            missing_alt = sum(1 for img in soup.find_all('img') if not str(img.get('alt') or '').strip())
            metrics['images_missing_alt'] = missing_alt
            if missing_alt >= 3:
                findings.append(f'{missing_alt} imagens sem texto alternativo.')
                score -= min(8, missing_alt)
    except Exception as exc:
        return {'ok': False, 'url': target, 'score': 0, 'findings': [f'Falha ao acessar site: {exc}'], 'metrics': metrics}

    browser = inspect_page(target, timeout_ms=20000)
    metrics['browser_available'] = bool(browser.get('ok'))
    if browser.get('ok'):
        metrics['rendered_title'] = browser.get('title')
        metrics['forms'] = browser.get('forms')
        metrics['buttons'] = browser.get('buttons')
        if not browser.get('has_viewport') and metrics.get('viewport'):
            findings.append('Viewport não detectado no navegador renderizado.')
            score -= 3

    score = max(0, min(score, 100))
    grade = 'A' if score >= 90 else 'B' if score >= 75 else 'C' if score >= 60 else 'D' if score >= 40 else 'E'
    return {'ok': True, 'url': target, 'score': score, 'grade': grade, 'findings': findings, 'metrics': metrics}


def format_audit(report: dict[str, Any]) -> str:
    if not report.get('ok'):
        return '\n'.join(report.get('findings') or ['Falha na auditoria.'])
    lines = [f"Auditoria: {report.get('url')}", f"Score: {report.get('score')}/100 ({report.get('grade')})"]
    findings = report.get('findings') or []
    if findings:
        lines.append('Problemas encontrados:')
        lines.extend(f'- {item}' for item in findings)
    else:
        lines.append('Nenhum problema básico relevante detectado.')
    return '\n'.join(lines)
