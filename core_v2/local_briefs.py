#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import feedparser
import httpx

UA = "HermesCore/2.0 (+local-first)"
TIMEOUT = 10.0
MAX_ITEMS = 6
ROOT = Path.home() / ".hermes" / "core-v2"
STATE = ROOT / "state"

FEEDS = {
    "ai": [
        ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
        ("Google AI", "https://blog.google/technology/ai/rss/"),
        ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
        ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ],
    "marketing": [
        ("Search Engine Journal", "https://www.searchenginejournal.com/feed/"),
        ("HubSpot Marketing", "https://blog.hubspot.com/marketing/rss.xml"),
        ("Moz", "https://moz.com/blog/feed"),
    ],
    "product": [
        ("Product Hunt", "https://www.producthunt.com/feed"),
        ("Hacker News", "https://hnrss.org/frontpage"),
        ("TechCrunch Startups", "https://techcrunch.com/category/startups/feed/"),
    ],
}


def clean(text: str, limit: int = 180) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def fetch_feed(source: str, url: str) -> list[dict]:
    try:
        with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": UA}, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
        parsed = feedparser.parse(r.content)
    except Exception as exc:
        return [{"source": source, "error": str(exc)}]

    items = []
    for e in parsed.entries[:5]:
        title = clean(getattr(e, "title", ""), 140)
        link = getattr(e, "link", "") or ""
        summary = clean(getattr(e, "summary", "") or getattr(e, "description", ""), 180)
        if title:
            items.append({"source": source, "title": title, "link": link, "summary": summary})
    return items


def dedupe(items: Iterable[dict]) -> list[dict]:
    seen = set()
    out = []
    for item in items:
        if item.get("error"):
            continue
        key = re.sub(r"\W+", "", item.get("title", "").lower())[:80]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def render_news(kind: str, title: str) -> str:
    collected: list[dict] = []
    errors: list[str] = []
    for source, url in FEEDS[kind]:
        rows = fetch_feed(source, url)
        for row in rows:
            if row.get("error"):
                errors.append(f"{source}: {row['error'][:90]}")
            else:
                collected.append(row)

    items = dedupe(collected)[:MAX_ITEMS]
    now = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")
    lines = [f"{title}", f"Atualizado: {now}", ""]
    if not items:
        lines.append("Nenhuma notícia foi coletada agora.")
    else:
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. {item['title']} — {item['source']}")
            if item.get("summary"):
                lines.append(f"   {item['summary']}")
            if item.get("link"):
                lines.append(f"   {item['link']}")
    if errors:
        lines.extend(["", f"Fontes indisponíveis: {len(errors)}"])
    return "\n".join(lines)


def render_finance() -> str:
    path = STATE / "subscriptions.json"
    now = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")
    lines = ["Financial Brief - Assinaturas", f"Atualizado: {now}", ""]
    if not path.exists():
        lines.append("Nenhuma assinatura local configurada ainda.")
        lines.append(f"Configure em: {path}")
        return "\n".join(lines)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return "\n".join(lines + [f"Erro lendo subscriptions.json: {exc}"])

    rows = data if isinstance(data, list) else data.get("subscriptions", [])
    if not rows:
        lines.append("Nenhuma assinatura cadastrada.")
        return "\n".join(lines)

    total = 0.0
    for i, row in enumerate(rows, 1):
        name = str(row.get("name", "Assinatura"))
        value = float(row.get("value", 0) or 0)
        currency = row.get("currency", "BRL")
        billing = row.get("billing", "mensal")
        next_date = row.get("next_date", "-")
        active = bool(row.get("active", True))
        if active:
            total += value
        status = "ativa" if active else "pausada"
        lines.append(f"{i}. {name}: {currency} {value:.2f} | {billing} | próxima: {next_date} | {status}")
    lines.extend(["", f"Total ativo informado: {total:.2f} (sem conversão cambial)"])
    return "\n".join(lines)


def main() -> int:
    kind = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if kind == "ai":
        print(render_news("ai", "AI Daily Brief"))
    elif kind == "marketing":
        print(render_news("marketing", "Marketing & Leads Brief"))
    elif kind == "product":
        print(render_news("product", "Daily Product Opportunity Brief"))
    elif kind == "finance":
        print(render_finance())
    else:
        print("Uso: local_briefs.py ai|marketing|product|finance", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
