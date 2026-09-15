from __future__ import annotations

import re
from collections import deque
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

USER_AGENT = 'HermesLocal/5.0 (+local autonomous research)'


def _normalize(url: str) -> str:
    raw = str(url or '').strip()
    if not raw.startswith(('http://', 'https://')):
        raw = 'https://' + raw
    return raw


def _asset(base: str, value: str) -> str | None:
    raw = str(value or '').strip()
    if not raw or raw.startswith(('data:', 'javascript:', '#')):
        return None
    absolute = urljoin(base, raw)
    parsed = urlparse(absolute)
    if parsed.scheme not in {'http', 'https'}:
        return None
    low = absolute.casefold()
    if low.endswith(('.svg', '.ico')) or 'sprite' in low:
        return None
    return absolute


def crawl(url: str, max_pages: int = 5) -> dict[str, Any]:
    start = _normalize(url)
    host = urlparse(start).netloc.casefold()
    queue = deque([start])
    seen: set[str] = set()
    pages: list[dict[str, Any]] = []
    contacts: set[str] = set()
    socials: set[str] = set()
    images: set[str] = set()
    logos: set[str] = set()

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
                base = str(r.url)
                soup = BeautifulSoup(r.text, 'html.parser')
                title = soup.title.get_text(' ', strip=True) if soup.title else ''
                desc_tag = soup.find('meta', attrs={'name': re.compile('description', re.I)})
                description = desc_tag.get('content', '').strip() if desc_tag else ''
                text = soup.get_text(' ', strip=True)
                pages.append({'url': base, 'status': r.status_code, 'title': title, 'description': description, 'text': text[:12000]})

                for tag in soup.find_all('meta'):
                    prop = str(tag.get('property') or tag.get('name') or '').casefold()
                    if prop in {'og:image', 'twitter:image', 'twitter:image:src'}:
                        asset = _asset(base, str(tag.get('content') or ''))
                        if asset:
                            images.add(asset)

                for img in soup.find_all('img'):
                    asset = _asset(base, str(img.get('src') or img.get('data-src') or ''))
                    if asset:
                        images.add(asset)
                        marker = ' '.join([
                            str(img.get('alt') or ''),
                            str(img.get('class') or ''),
                            str(img.get('id') or ''),
                            asset,
                        ]).casefold()
                        if 'logo' in marker or 'brand' in marker:
                            logos.add(asset)
                    if len(images) >= 30:
                        break

                for a in soup.find_all('a', href=True):
                    href = str(a.get('href') or '').strip()
                    if href.startswith('mailto:') or href.startswith('tel:') or 'wa.me/' in href or 'api.whatsapp.com' in href:
                        contacts.add(href)
                    if any(domain in href for domain in ('instagram.com', 'facebook.com', 'linkedin.com', 'youtube.com', 'tiktok.com')):
                        socials.add(href)
                    absolute = urljoin(base, href)
                    parsed = urlparse(absolute)
                    if parsed.netloc.casefold() == host and parsed.scheme in {'http', 'https'}:
                        clean = parsed._replace(fragment='').geturl()
                        if clean not in seen and len(queue) < 50:
                            queue.append(clean)
            except Exception as exc:
                pages.append({'url': current, 'error': str(exc)})

    return {
        'ok': any(p.get('status') and int(p['status']) < 400 for p in pages),
        'start_url': start,
        'pages': pages,
        'contacts': sorted(contacts),
        'socials': sorted(socials),
        'images': sorted(images)[:20],
        'logos': sorted(logos)[:5],
    }
