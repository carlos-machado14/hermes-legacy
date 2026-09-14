from __future__ import annotations

import re
from collections import deque
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

USER_AGENT = 'HermesLocal/4.1 (+local autonomous research)'


def _normalize(url: str) -> str:
    raw = str(url or '').strip()
    if not raw.startswith(('http://', 'https://')):
        raw = 'https://' + raw
    return raw


def crawl(url: str, max_pages: int = 5) -> dict[str, Any]:
    start = _normalize(url)
    host = urlparse(start).netloc
    queue = deque([start])
    seen: set[str] = set()
    pages: list[dict[str, Any]] = []
    contacts: set[str] = set()
    socials: set[str] = set()

    with httpx.Client(timeout=15.0, follow_redirects=True, headers={'User-Agent': USER_AGENT}) as client:
        while queue and len(pages) < max(1, min(int(max_pages), 12)):
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            try:
                r = client.get(current)
                ctype = r.headers.get('content-type', '')
                if r.status_code >= 400 or 'text/html' not in ctype:
                    pages.append({'url': current, 'status': r.status_code, 'error': 'not_html_or_http_error'})
                    continue
                soup = BeautifulSoup(r.text, 'html.parser')
                title = soup.title.get_text(' ', strip=True) if soup.title else ''
                desc_tag = soup.find('meta', attrs={'name': re.compile('description', re.I)})
                description = desc_tag.get('content', '').strip() if desc_tag else ''
                text = soup.get_text(' ', strip=True)
                pages.append({'url': str(r.url), 'status': r.status_code, 'title': title, 'description': description, 'text': text[:12000]})

                for a in soup.find_all('a', href=True):
                    href = str(a.get('href') or '').strip()
                    if href.startswith('mailto:') or href.startswith('tel:') or 'wa.me/' in href or 'api.whatsapp.com' in href:
                        contacts.add(href)
                    if any(domain in href for domain in ('instagram.com', 'facebook.com', 'linkedin.com', 'youtube.com', 'tiktok.com')):
                        socials.add(href)
                    absolute = urljoin(str(r.url), href)
                    parsed = urlparse(absolute)
                    if parsed.netloc == host and parsed.scheme in {'http', 'https'}:
                        clean = parsed._replace(fragment='').geturl()
                        if clean not in seen and len(queue) < 50:
                            queue.append(clean)
            except Exception as exc:
                pages.append({'url': current, 'error': str(exc)})

    return {'ok': any(p.get('status') and int(p['status']) < 400 for p in pages), 'start_url': start, 'pages': pages, 'contacts': sorted(contacts), 'socials': sorted(socials)}
