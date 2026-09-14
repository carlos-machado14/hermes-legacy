#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

HOME = Path.home()
HERMES = HOME / '.hermes'
CORE_STATE = HERMES / 'core-v2' / 'state'

SKIP_PARTS = {
    'venv', '.git', 'node_modules', 'models', 'model', 'cache', '__pycache__',
    'logs', 'workspaces', 'searxng', 'hermes-agent',
}
TEXT_SUFFIXES = {'.json', '.md', '.txt', '.yaml', '.yml'}
MONEY_RE = re.compile(r'(?:R\$\s*\d|US\$\s*\d|\$\s*\d|€\s*\d|\bBRL\b|\bUSD\b|\bEUR\b|\b\d+[\.,]\d{2}\b)', re.I)
FINANCE_RE = re.compile(r'\b(assinatur(?:a|as)|subscription|mensalidade|cobran[cç]a|pagamento|recorrente|recurring|plano|fatura)\b', re.I)
BILLING_RE = re.compile(r'\b(mensal|mensalmente|anual|anualmente|weekly|monthly|yearly|semanal|renova|renova[cç][aã]o)\b', re.I)


def _safe_files() -> list[Path]:
    roots = [
        CORE_STATE,
        HERMES / 'state',
        HERMES / 'data',
        HERMES / 'memory',
        HERMES / 'cron',
        HERMES / 'crons',
        HERMES / 'sessions',
        HERMES / 'scripts',
    ]
    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        try:
            iterator = root.rglob('*') if root.is_dir() else [root]
            for path in iterator:
                if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                if any(part in SKIP_PARTS for part in path.parts):
                    continue
                try:
                    if path.stat().st_size > 2_000_000:
                        continue
                except OSError:
                    continue
                key = str(path)
                if key not in seen:
                    seen.add(key)
                    out.append(path)
        except Exception:
            continue
    return out[:3000]


def _numeric(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return True
    if not isinstance(value, str):
        return False
    raw = value.strip().replace('R$', '').replace('US$', '').replace('€', '').replace(' ', '')
    raw = raw.replace('.', '').replace(',', '.') if ',' in raw else raw
    try:
        float(raw)
        return True
    except Exception:
        return False


def _looks_like_subscription(row: dict[str, Any]) -> bool:
    keys = {str(k).casefold() for k in row}
    name_keys = {'name', 'nome', 'title', 'titulo', 'título', 'service', 'servico', 'serviço'}
    value_keys = {'value', 'valor', 'amount', 'price', 'preco', 'preço', 'cost', 'custo'}
    billing_keys = {'billing', 'period', 'periodicidade', 'ciclo', 'frequency', 'frequencia', 'frequência', 'next_date', 'nextdate', 'proxima_cobranca', 'próxima_cobrança'}
    has_name = bool(keys & name_keys)
    has_value = any(k.casefold() in value_keys and _numeric(v) for k, v in row.items())
    has_billing = bool(keys & billing_keys)
    return has_name and has_value and (has_billing or 'active' in keys or 'ativo' in keys)


def _walk_rows(value: Any, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 8:
        return []
    out: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if _looks_like_subscription(value):
            out.append(value)
        for key, child in value.items():
            low = str(key).casefold()
            if low in {'subscriptions', 'assinaturas', 'recurring', 'recorrentes', 'payments', 'pagamentos'}:
                out.extend(_walk_rows(child, depth + 1))
            elif depth < 3:
                out.extend(_walk_rows(child, depth + 1))
    elif isinstance(value, list):
        for child in value[:500]:
            out.extend(_walk_rows(child, depth + 1))
    return out


def structured_rows() -> tuple[list[dict[str, Any]], Path | None]:
    preferred = [
        CORE_STATE / 'subscriptions.json',
        HERMES / 'state' / 'subscriptions.json',
        HERMES / 'subscriptions.json',
        HERMES / 'data' / 'subscriptions.json',
        HERMES / 'memory' / 'subscriptions.json',
        HERMES / 'memory' / 'finance' / 'subscriptions.json',
        HERMES / 'memory' / 'financeiro' / 'subscriptions.json',
    ]
    files = preferred + [p for p in _safe_files() if p.suffix.lower() == '.json' and p not in preferred]
    seen: set[str] = set()
    for path in files:
        key = str(path)
        if key in seen or not path.exists():
            continue
        seen.add(key)
        try:
            data = json.loads(path.read_text(encoding='utf-8', errors='ignore'))
        except Exception:
            continue
        rows = _walk_rows(data)
        if rows:
            unique: list[dict[str, Any]] = []
            fingerprints: set[str] = set()
            for row in rows:
                fp = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
                if fp not in fingerprints:
                    fingerprints.add(fp)
                    unique.append(row)
            return unique[:100], path
    return [], None


def _is_generated_or_prompt_source(path: Path) -> bool:
    low = str(path).casefold()
    name = path.name.casefold()
    if name in {'personal_profile.json', 'jobs.json'}:
        return True
    if '/memory/profile/' in low:
        return True
    if '/cron/output/' in low or '/crons/output/' in low:
        return True
    return False


def evidence_snippets(limit: int = 8) -> list[dict[str, str]]:
    """Procura somente evidência financeira concreta; prompts/briefings não contam como dados."""
    found: list[dict[str, str]] = []
    for path in _safe_files():
        if _is_generated_or_prompt_source(path):
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            window = ' '.join(x.strip() for x in lines[max(0, i - 1): min(len(lines), i + 2)] if x.strip())
            # Para ser dado real, exige simultaneamente assunto financeiro + valor/moeda.
            # Periodicidade sozinha (ex.: "Monthly Recurring Revenue") não é suficiente.
            if not FINANCE_RE.search(window) or not MONEY_RE.search(window):
                continue
            if len(window) > 500:
                window = window[:497].rstrip() + '...'
            found.append({'path': str(path), 'snippet': re.sub(r'\s+', ' ', window).strip()})
            if len(found) >= limit:
                return found
    return found


def routine_inventory() -> list[dict[str, str]]:
    """Mostra rotinas financeiras separadamente; rotina não é tratada como base de dados."""
    path = HERMES / 'cron' / 'jobs.json'
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8', errors='ignore'))
    except Exception:
        return []
    jobs = data if isinstance(data, list) else data.get('jobs', []) if isinstance(data, dict) else []
    out: list[dict[str, str]] = []
    for job in jobs if isinstance(jobs, list) else []:
        if not isinstance(job, dict):
            continue
        blob = json.dumps(job, ensure_ascii=False).casefold()
        if any(k in blob for k in ('financial brief', 'finanças', 'financas', 'assinatura')):
            out.append({
                'id': str(job.get('id') or ''),
                'name': str(job.get('name') or ''),
                'schedule': str(job.get('schedule') or job.get('cron') or ''),
            })
    return out[:20]


def diagnostic() -> dict[str, Any]:
    rows, source = structured_rows()
    evidence = [] if rows else evidence_snippets()
    return {
        'structured_rows': rows,
        'structured_source': str(source) if source else None,
        'evidence': evidence,
        'finance_routines': routine_inventory(),
    }
