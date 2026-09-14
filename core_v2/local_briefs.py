#!/usr/bin/env python3
from __future__ import annotations

import html
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, Any

import feedparser
import httpx

from finance_data_resolver import diagnostic as finance_diagnostic

UA = "HermesCore/2.0 (+local-first)"
TIMEOUT = 10.0
MAX_ITEMS = 6
HOME = Path.home()
ROOT = HOME / ".hermes" / "core-v2"
STATE = ROOT / "state"

FEEDS = {
    "ai": [
        ("Notícias de IA", "https://news.google.com/rss/search?q=intelig%C3%AAncia+artificial+IA+tecnologia&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
        ("IA e modelos", "https://news.google.com/rss/search?q=OpenAI+Google+Gemini+Claude+modelos+IA&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
    ],
    "marketing": [
        ("Marketing Digital", "https://news.google.com/rss/search?q=marketing+digital+vendas+leads+Brasil&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
        ("Negócios e aquisição", "https://news.google.com/rss/search?q=neg%C3%B3cios+aquisi%C3%A7%C3%A3o+clientes+SEO+redes+sociais&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
    ],
    "product": [
        ("Startups e Produtos", "https://news.google.com/rss/search?q=startups+novos+produtos+tecnologia+Brasil&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
        ("SaaS e oportunidades", "https://news.google.com/rss/search?q=SaaS+aplicativos+inova%C3%A7%C3%A3o+oportunidades+neg%C3%B3cios&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
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
    seen = set(); out = []
    for item in items:
        if item.get("error"):
            continue
        key = re.sub(r"\W+", "", item.get("title", "").lower())[:100]
        if not key or key in seen:
            continue
        seen.add(key); out.append(item)
    return out


def render_news(kind: str, title: str, intro: str) -> str:
    collected: list[dict] = []; errors: list[str] = []
    for source, url in FEEDS[kind]:
        for row in fetch_feed(source, url):
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


def _row_value(row: dict, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return default


def _money_value(raw_value: Any) -> float:
    raw = str(raw_value).strip().replace("R$", "").replace("US$", "").replace("€", "").replace(" ", "")
    try:
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        return float(raw)
    except Exception:
        return 0.0


def _brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _render_canonical_finance(now: str) -> str | None:
    try:
        from finance_manager import load, totals
        data = load()
    except Exception:
        return None
    expenses = [x for x in data.get('expenses', []) if isinstance(x, dict)]
    groups = [x for x in data.get('subscription_groups', []) if isinstance(x, dict)]
    subscriptions = [x for x in data.get('subscriptions', []) if isinstance(x, dict)]
    income = data.get('income') if isinstance(data.get('income'), dict) else {}
    if not expenses and not groups and not subscriptions and not income:
        return None

    t = totals(data)
    lines = ["🇧🇷 Resumo Financeiro — Base pessoal", f"Atualizado em: {now}", ""]
    if t['income']:
        lines.append(f"💰 Renda mensal informada: {_brl(t['income'])}")
        lines.append("")

    if groups or subscriptions:
        lines.append("💳 Assinaturas")
        for group in groups:
            if not group.get('active', True):
                continue
            name = str(group.get('name') or 'Assinaturas')
            value = _money_value(group.get('monthly_total'))
            members = group.get('members') or []
            detail = f" — {', '.join(str(x) for x in members)}" if isinstance(members, list) and members else ""
            lines.append(f"• {name}: {_brl(value)}{detail}")
        for item in subscriptions:
            if not item.get('active', True):
                continue
            name = str(item.get('name') or 'Assinatura')
            value = _money_value(item.get('monthly_value', item.get('monthly_total')))
            lines.append(f"• {name}: {_brl(value)}")
        lines.append(f"Subtotal assinaturas: {_brl(t['subscriptions'])}")
        lines.append("")

    if expenses:
        lines.append("🏠 Contas e despesas recorrentes")
        for item in expenses:
            if not item.get('active', True):
                continue
            name = str(item.get('name') or 'Despesa')
            value = _money_value(item.get('monthly_value'))
            suffix = ''
            remaining = item.get('remaining_installments')
            if remaining not in (None, ''):
                suffix += f" | {remaining} parcelas restantes"
            until = item.get('until')
            if until:
                suffix += f" | até {until}"
            lines.append(f"• {name}: {_brl(value)}{suffix}")
        lines.append(f"Subtotal contas/despesas: {_brl(t['expenses'])}")
        lines.append("")

    lines.append(f"📊 Total mensal recorrente conhecido: {_brl(t['total'])}")
    if t['income']:
        lines.append(f"Comprometimento da renda: {t['commitment_pct']:.1f}%")
        lines.append(f"Saldo após esses custos fixos: {_brl(t['free_after_fixed'])}")

    notes = [str(x) for x in data.get('notes', []) if str(x).strip()]
    if notes:
        lines.append("")
        lines.append("📝 Observações")
        for note in notes[:8]:
            lines.append(f"• {note}")
    lines.append("")
    lines.append("Fonte: base financeira local estruturada do Hermes.")
    return "\n".join(lines)


def render_finance() -> str:
    now = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")
    canonical = _render_canonical_finance(now)
    if canonical:
        return canonical

    lines = ["🇧🇷 Resumo Financeiro — Assinaturas", f"Atualizado em: {now}", ""]
    resolved = finance_diagnostic()
    rows = list(resolved.get("structured_rows") or [])
    source = resolved.get("structured_source")

    if rows:
        total_by_currency: dict[str, float] = {}
        for i, row in enumerate(rows, 1):
            name = str(_row_value(row, "name", "nome", "title", "titulo", "título", "service", "servico", "serviço", default="Assinatura"))
            raw_value = _row_value(row, "value", "valor", "amount", "price", "preco", "preço", "cost", "custo", default=0)
            value = _money_value(raw_value)
            currency = str(_row_value(row, "currency", "moeda", default="BRL"))
            billing = _row_value(row, "billing", "period", "periodicidade", "ciclo", "frequency", "frequencia", "frequência", default="mensal")
            next_date = _row_value(row, "next_date", "nextDate", "proxima_cobranca", "próxima_cobrança", default="-")
            active_raw = _row_value(row, "active", "ativo", default=True)
            active = bool(active_raw) if not isinstance(active_raw, str) else active_raw.casefold() not in {"false", "0", "nao", "não", "inativa", "pausada"}
            if active:
                total_by_currency[currency] = total_by_currency.get(currency, 0.0) + value
            status = "ativa" if active else "pausada"
            lines.append(f"{i}. {name}: {currency} {value:.2f} | {billing} | próxima cobrança: {next_date} | {status}")
        lines.append("")
        for currency, total in sorted(total_by_currency.items()):
            lines.append(f"Total ativo em {currency}: {total:.2f}")
        if source:
            lines.append(f"Fonte local recuperada: {source}")
        return "\n".join(lines)

    declared = list(resolved.get("legacy_declared_subscriptions") or [])
    declared_source = resolved.get("legacy_declared_source")
    if declared:
        lines.append("✅ Recuperei da sua sessão antiga as assinaturas que você declarou explicitamente:")
        lines.append("")
        for i, name in enumerate(declared, 1):
            lines.append(f"{i}. {name} — valor ainda não recuperado")
        lines.append("")
        lines.append("Esses nomes vieram de uma mensagem sua, não de estimativa do Hermes.")
        lines.append("Os valores exatos não apareceram nessa sessão; nela você escolheu simular valores estimados. Por isso não vou gravar preços inventados como se fossem seus gastos reais.")
        if declared_source:
            lines.append(f"Fonte recuperada: {declared_source}")
        return "\n".join(lines)

    evidence = list(resolved.get("evidence") or [])
    if evidence:
        lines.append("⚠️ Encontrei trechos com assunto financeiro e valores, mas eles não estão estruturados o suficiente para assumir que são seus gastos.")
        lines.append("")
        for item in evidence[:8]:
            lines.append(f"• Fonte: {item.get('path')}")
            lines.append(f"  {item.get('snippet')}")
        lines.append("")
        lines.append("Não vou transformar pesquisas web, respostas do agente ou estimativas em despesas reais automaticamente.")
        return "\n".join(lines)

    lines.append("⚠️ Não encontrei uma base estruturada nem uma lista explícita de assinaturas com valores reais.")
    lines.append("O Hermes não vai inventar ou substituir gastos ausentes.")
    return "\n".join(lines)


def main() -> int:
    kind = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    if kind == "ai":
        print(render_news("ai", "Resumo Diário de Inteligência Artificial", "Principais notícias e movimentos de IA selecionados para você:"))
    elif kind == "marketing":
        print(render_news("marketing", "Resumo de Marketing e Leads", "Destaques sobre aquisição de clientes, marketing e vendas:"))
    elif kind == "product":
        print(render_news("product", "Oportunidades de Produto e Negócios", "Sinais de mercado, startups, produtos e oportunidades relevantes:"))
    elif kind == "finance":
        print(render_finance())
    else:
        print("Uso: local_briefs.py ai|marketing|product|finance", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
