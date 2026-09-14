from __future__ import annotations

from typing import Any


def _load_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except Exception:
        return None


def available() -> bool:
    return _load_playwright() is not None


def inspect_page(url: str, timeout_ms: int = 30000) -> dict[str, Any]:
    sync_playwright = _load_playwright()
    if sync_playwright is None:
        return {'ok': False, 'error': 'playwright_not_installed', 'url': url}
    target = str(url or '').strip()
    if not target.startswith(('http://', 'https://')):
        target = 'https://' + target
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1366, 'height': 900})
            response = page.goto(target, wait_until='domcontentloaded', timeout=timeout_ms)
            page.wait_for_timeout(750)
            data = {
                'ok': True,
                'url': page.url,
                'status': response.status if response else None,
                'title': page.title(),
                'text': page.locator('body').inner_text(timeout=5000)[:20000],
                'links': page.locator('a').evaluate_all("els => els.slice(0,80).map(a => ({text:(a.innerText||'').trim(), href:a.href}))"),
                'has_viewport': page.locator('meta[name="viewport"]').count() > 0,
                'forms': page.locator('form').count(),
                'images': page.locator('img').count(),
                'buttons': page.locator('button').count(),
            }
            browser.close()
            return data
    except Exception as exc:
        return {'ok': False, 'error': str(exc), 'url': target}
