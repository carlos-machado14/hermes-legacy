#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

import feedparser
import httpx

UA = "HermesCore/2.0 (+local-first)"
TIMEOUT = 10.0
MAX_ITEMS = 6
ROOT = Path.home() / ".hermes" / "core-v2"
STATE = ROOT / "state"

# Todas as fontes de notícias são consultadas com localização pt-BR para que
# as crons entreguem conteúdo em português sem depender do LLM para tradução.
FEEDS = {
    "ai": [
        (
            "Notícias de IA",
            "https://news.google.com/rss/search?q=intelig%C3%AAncia+artificial+IA+tecnologia&hl=pt-BR&gl=BR&ceid=BR:pt-419",
        ),
        (
            "IA e modelos",
            "https://news.google.com/rss/search?q=OpenAI+Google+Gemini+Claude+modelos+IA&hl=pt-BR&gl=BR&ceid=BR:pt-419",
        ),
    ],
    "marketing": [
        (
            "Marketing Digital",
            "https://news.google.com/rss/search?q=marketing+digital+vendas+leads+Brasil&hl=pt-BR&gl=BR&ceid=BR:pt-419",
        ),
        (
            "Negócios e aquisição",
            "https://news.google.com/rss/search?q=neg%C3%B3cios+aquisi%C3%A7%C3%A3o+clientes+SEO+redes+sociais&hl=pt-BR&gl=BR&ceid=BR:pt-419",
        ),
    ],
    "product": [
        (
            "Startups e Produtos",
            "https://news.google.com/rss/search?q=startups+novos+produtos+tecnologia+Brasil&hl=pt-BR&gl=BR&ceid=BR:pt-419",
        ),
        (
            "SaaS e oportunidades",
            "https://news.google.com/rss/search?q=SaaS+aplicativos+inova%C3%A7%C3%A3o+oportunidades+neg%C3%B3cios&hl=pt-BR&gl=BR&ceid=BR:pt-419",
        ),
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
    for e in parsed.entries[:8]:
        title = clean(getattr(e, "title", ""), 170)
        link = getattr(e, "link", "") or ""
        if title:
            items.append({"source": source, "title": title, "link": link})
    return items


def dedupe(items: Iterable[dict]) -> list[dict]:
    seen = set()
    out = []
    for item in items:
        if item.get("error"):
            continue
        key = re.sub(r"\W+", "", item.get("title", "").lower())[:100]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def render_news(kind: str, title: str, intro: str) -> str:
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
    lines = [f"🇧🇷 {title}", f"Atualizado em: {now}", "", intro, ""]
    if not items:
        lines.append("Nenhuma notícia relevante foi encontrada neste momento.")
    else:
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. {item['title']}")
            if item.get("link"):
                lines.append(f"   🔗 {item['link']}")
            lines.append("")
    if errors:
        lines.append(f"⚠️ Fontes temporariamente indisponíveis: {len(errors)}")
    lines.append("Conteúdo coletado automaticamente pelo Hermes na VPS.")
    return "\n".join(lines).strip()


def render_finance() -> str:
    path = STATE / "subscriptions.json"
    now = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")
    lines = ["🇧🇷 Resumo Financeiro — Assinaturas", f"Atualizado em: {now}", ""]
    if not path.exists():
        lines.append("Nenhuma assinatura local foi configurada ainda.")
        lines.append(f"Arquivo de configuração: {path}")
        return "\n".join(lines)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return "\n".join(lines + [f"Erro ao ler o arquivo de assinaturas: {exc}"])

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
        lines.append(f"{i}. {name}: {currency} {value:.2f} | {billing} | próxima cobrança: {next_date} | {status}")
    lines.extend(["", f"Total ativo informado: {total:.2f} (sem conversão cambial)"])
    return "\n".join(lines)


def main() -> int:
    kind = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if kind == "ai":
        print(render_news(
            "ai",
            "Resumo Diário de Inteligência Artificial",
            "Principais notícias e movimentos de IA selecionados para você:",
        ))
    elif kind == "marketing":
        print(render_news(
            "marketing",
            "Resumo de Marketing e Leads",
            "Destaques sobre aquisição de clientes, marketing e vendas:",
        ))
    elif kind == "product":
        print(render_news(
            "product",
            "Oportunidades de Produto e Negócios",
            "Sinais de mercado, startups, produtos e oportunidades relevantes:",
        ))
    elif kind == "finance":
        print(render_finance())
    else:
        print("Uso: local_briefs.py ai|marketing|product|finance", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
