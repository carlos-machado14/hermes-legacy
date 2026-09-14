#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, Any

import feedparser
import httpx

UA = "HermesCore/2.0 (+local-first)"
TIMEOUT = 10.0
MAX_ITEMS = 6
HOME = Path.home()
ROOT = HOME / ".hermes" / "core-v2"
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


def _subscription_candidates() -> list[Path]:
    """Locais atuais + legados. Nunca move/apaga dados do usuário."""
    candidates = [
        STATE / "subscriptions.json",
        HOME / ".hermes" / "state" / "subscriptions.json",
        HOME / ".hermes" / "subscriptions.json",
        HOME / ".hermes" / "data" / "subscriptions.json",
        HOME / ".hermes" / "memory" / "subscriptions.json",
        HOME / ".hermes" / "memory" / "finance" / "subscriptions.json",
        HOME / ".hermes" / "memory" / "financeiro" / "subscriptions.json",
    ]
    # Alguns installs antigos usavam nomes em português/financeiro. Busca limitada
    # apenas dentro de ~/.hermes e sem seguir outros diretórios do sistema.
    root = HOME / ".hermes"
    try:
        for path in root.rglob("*.json"):
            low = path.name.casefold()
            if any(k in low for k in ("subscription", "assinatura", "finance", "financeiro")):
                candidates.append(path)
    except Exception:
        pass
    unique: list[Path] = []
    seen: set[str] = set()
    for p in candidates:
        key = str(p)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique[:50]


def _extract_rows(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("subscriptions", "assinaturas", "items", "recurring", "recorrentes"):
        rows = data.get(key)
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
    return []


def _load_finance_rows() -> tuple[list[dict], Path | None]:
    for path in _subscription_candidates():
        if not path.exists() or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            rows = _extract_rows(data)
            if rows:
                return rows, path
        except Exception:
            continue
    return [], None


def _memory_finance_context() -> str:
    try:
        from memory_vault import retrieve, refresh_index
        refresh_index()
        return retrieve(
            "assinaturas financeiro pagamentos gastos recorrentes cobrança mensal mensalidade",
            limit=6,
            max_chars=5000,
        ).strip()
    except Exception:
        return ""


def _row_value(row: dict, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return default


def render_finance() -> str:
    now = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")
    lines = ["🇧🇷 Resumo Financeiro — Assinaturas", f"Atualizado em: {now}", ""]
    rows, source = _load_finance_rows()

    if not rows:
        memory = _memory_finance_context()
        if memory:
            lines.append("Encontrei contexto financeiro salvo na sua memória do Hermes, mas ele ainda não está estruturado no arquivo de assinaturas:")
            lines.append("")
            lines.append(memory)
            lines.append("")
            lines.append("⚠️ Não vou dizer que você não possui dados: o Hermes encontrou informações financeiras na memória. Para totalizar automaticamente, elas precisam estar em formato estruturado.")
            return "\n".join(lines)
        lines.append("⚠️ Não encontrei uma base estruturada de assinaturas nos locais atuais ou legados do Hermes.")
        lines.append("Se esses dados existiam antes, eles podem estar em outro arquivo da instalação antiga; o upgrade não deve substituí-los nem assumir que estão vazios.")
        return "\n".join(lines)

    total = 0.0
    for i, row in enumerate(rows, 1):
        name = str(_row_value(row, "name", "nome", "title", default="Assinatura"))
        raw_value = _row_value(row, "value", "valor", "amount", "price", default=0)
        try:
            value = float(str(raw_value).replace("R$", "").replace(" ", "").replace(",", "."))
        except Exception:
            value = 0.0
        currency = _row_value(row, "currency", "moeda", default="BRL")
        billing = _row_value(row, "billing", "period", "periodicidade", "ciclo", default="mensal")
        next_date = _row_value(row, "next_date", "nextDate", "proxima_cobranca", "próxima_cobrança", default="-")
        active_raw = _row_value(row, "active", "ativo", default=True)
        active = bool(active_raw) if not isinstance(active_raw, str) else active_raw.casefold() not in {"false", "0", "nao", "não", "inativa", "pausada"}
        if active:
            total += value
        status = "ativa" if active else "pausada"
        lines.append(f"{i}. {name}: {currency} {value:.2f} | {billing} | próxima cobrança: {next_date} | {status}")
    lines.extend(["", f"Total ativo informado: {total:.2f} (sem conversão cambial)"])
    if source is not None:
        lines.append(f"Fonte local recuperada: {source}")
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
