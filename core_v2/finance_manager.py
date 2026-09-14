#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

STATE = Path.home() / '.hermes' / 'core-v2' / 'state'
PROFILE = STATE / 'finance_profile.json'
HISTORY = STATE / 'finance_history'


def _empty() -> dict[str, Any]:
    return {
        'version': 2,
        'income': {},
        'expenses': [],
        'subscriptions': [],
        'subscription_groups': [],
        'notes': [],
    }


def load() -> dict[str, Any]:
    if not PROFILE.exists():
        return _empty()
    try:
        data = json.loads(PROFILE.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return _empty()
        base = _empty()
        base.update(data)
        for key in ('expenses', 'subscriptions', 'subscription_groups', 'notes'):
            if not isinstance(base.get(key), list):
                base[key] = []
        if not isinstance(base.get('income'), dict):
            base['income'] = {}
        return base
    except Exception:
        return _empty()


def _backup_current() -> None:
    if not PROFILE.exists():
        return
    HISTORY.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime('%Y%m%d-%H%M%S-%f')
    shutil.copy2(PROFILE, HISTORY / f'finance_profile-{stamp}.json')


def save(data: dict[str, Any], *, reason: str | None = None) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    _backup_current()
    data['version'] = 2
    data['updated_at'] = datetime.now().astimezone().isoformat()
    if reason:
        audit = data.setdefault('change_log', [])
        if isinstance(audit, list):
            audit.append({'at': data['updated_at'], 'reason': reason})
            if len(audit) > 100:
                del audit[:-100]
    tmp = PROFILE.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(PROFILE)


def _money(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value or '').strip().replace('R$', '').replace('US$', '').replace('€', '').replace(' ', '')
    try:
        if ',' in raw:
            raw = raw.replace('.', '').replace(',', '.')
        return float(raw)
    except Exception:
        return 0.0


def totals(data: dict[str, Any] | None = None) -> dict[str, float]:
    data = data or load()
    expenses = [x for x in data.get('expenses', []) if isinstance(x, dict) and x.get('active', True)]
    subscriptions = [x for x in data.get('subscriptions', []) if isinstance(x, dict) and x.get('active', True)]
    groups = [x for x in data.get('subscription_groups', []) if isinstance(x, dict) and x.get('active', True)]
    expense_total = sum(_money(x.get('monthly_value')) for x in expenses)
    individual_subscriptions = sum(_money(x.get('monthly_value', x.get('monthly_total'))) for x in subscriptions)
    grouped_subscriptions = sum(_money(x.get('monthly_total')) for x in groups)
    subscriptions_total = individual_subscriptions + grouped_subscriptions
    income = _money((data.get('income') or {}).get('monthly_net'))
    total = expense_total + subscriptions_total
    return {
        'expenses': expense_total,
        'subscriptions': subscriptions_total,
        'total': total,
        'income': income,
        'free_after_fixed': income - total,
        'commitment_pct': (total / income * 100.0) if income > 0 else 0.0,
    }


def _norm(text: str) -> str:
    text = unicodedata.normalize('NFKD', str(text or ''))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _tokens(text: str) -> set[str]:
    stop = {'de', 'da', 'do', 'das', 'dos', 'meu', 'minha', 'o', 'a', 'e', 'para', 'parcela'}
    return {x for x in _norm(text).split() if x and x not in stop}


def _best_named_item(data: dict[str, Any], text: str, *, include_groups: bool = True) -> tuple[str, dict[str, Any]] | None:
    query = _norm(text)
    qtokens = _tokens(text)
    candidates: list[tuple[float, str, dict[str, Any]]] = []
    collections = [('expense', data.get('expenses', [])), ('subscription', data.get('subscriptions', []))]
    if include_groups:
        collections.append(('group', data.get('subscription_groups', [])))
    for kind, rows in collections:
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            name = str(row.get('name') or '')
            if not name:
                continue
            n = _norm(name)
            ntokens = _tokens(name)
            score = 0.0
            if n and n in query:
                score += 10.0
            overlap = len(qtokens & ntokens)
            score += overlap * 2.0
            if ntokens and ntokens <= qtokens:
                score += 4.0
            # Evita escolher Combustível Moto para frases como "paguei a moto".
            if 'combustivel' in ntokens and 'combustivel' not in qtokens:
                score -= 4.0
            if score > 0:
                candidates.append((score, kind, row))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None
    return candidates[0][1], candidates[0][2]


def _fmt_brl(value: float) -> str:
    return f'R$ {value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def summary(data: dict[str, Any] | None = None) -> str:
    data = data or load()
    t = totals(data)
    lines = ['💰 Resumo financeiro local', '']
    income = t['income']
    if income:
        lines.append(f"Renda mensal: {_fmt_brl(income)}")
    lines.append(f"Contas fixas: {_fmt_brl(t['expenses'])}")
    lines.append(f"Assinaturas: {_fmt_brl(t['subscriptions'])}")
    lines.append(f"Total recorrente conhecido: {_fmt_brl(t['total'])}")
    if income:
        lines.append(f"Comprometimento: {t['commitment_pct']:.1f}%")
        lines.append(f"Livre após fixos informados: {_fmt_brl(t['free_after_fixed'])}")
    lines.append('')
    active_expenses = [x for x in data.get('expenses', []) if isinstance(x, dict) and x.get('active', True)]
    if active_expenses:
        lines.append('Contas:')
        for row in active_expenses:
            lines.append(f"• {row.get('name')}: {_fmt_brl(_money(row.get('monthly_value')))}")
    groups = [x for x in data.get('subscription_groups', []) if isinstance(x, dict) and x.get('active', True)]
    subs = [x for x in data.get('subscriptions', []) if isinstance(x, dict) and x.get('active', True)]
    if groups or subs:
        lines.append('')
        lines.append('Assinaturas:')
        for row in groups:
            members = ', '.join(str(x) for x in row.get('members', []) if x)
            suffix = f" ({members})" if members else ''
            lines.append(f"• {row.get('name')}: {_fmt_brl(_money(row.get('monthly_total')))}{suffix}")
        for row in subs:
            lines.append(f"• {row.get('name')}: {_fmt_brl(_money(row.get('monthly_value', row.get('monthly_total'))))}")
    return '\n'.join(lines)


def set_income(value: float, *, source_text: str = '') -> str:
    data = load()
    data.setdefault('income', {})['monthly_net'] = float(value)
    data['income']['currency'] = 'BRL'
    save(data, reason=f'renda atualizada: {source_text or value}')
    return f"Renda mensal atualizada para {_fmt_brl(value)}.\n\n{summary(data)}"


def set_item_value(text: str, value: float) -> str | None:
    data = load()
    found = _best_named_item(data, text)
    if found is None:
        return None
    kind, row = found
    old = _money(row.get('monthly_total') if kind == 'group' else row.get('monthly_value'))
    field = 'monthly_total' if kind == 'group' else 'monthly_value'
    row[field] = float(value)
    row['active'] = True
    save(data, reason=f"{row.get('name')} de {old:.2f} para {value:.2f}: {text}")
    return f"Atualizei {row.get('name')}: {_fmt_brl(old)} → {_fmt_brl(value)}.\n\n{summary(data)}"


def deactivate_item(text: str) -> str | None:
    data = load()
    found = _best_named_item(data, text)
    if found is None:
        return None
    _, row = found
    row['active'] = False
    save(data, reason=f"desativado {row.get('name')}: {text}")
    return f"Marquei {row.get('name')} como encerrado/inativo. Ele não entra mais no total mensal.\n\n{summary(data)}"


def reactivate_item(text: str) -> str | None:
    data = load()
    found = _best_named_item(data, text)
    if found is None:
        return None
    _, row = found
    row['active'] = True
    save(data, reason=f"reativado {row.get('name')}: {text}")
    return f"Reativei {row.get('name')} no financeiro.\n\n{summary(data)}"


def add_item(name: str, value: float, *, kind: str = 'expense', details: str | None = None) -> str:
    data = load()
    name = re.sub(r'\s+', ' ', name).strip(' .,-:')
    if not name:
        return 'Não consegui identificar o nome do gasto/assinatura.'
    existing = _best_named_item(data, name)
    if existing is not None:
        _, row = existing
        return f"{row.get('name')} já existe no financeiro. Diga, por exemplo, “{row.get('name')} agora é 120” para alterar o valor."
    row: dict[str, Any] = {'name': name, 'monthly_value': float(value), 'currency': 'BRL', 'active': True}
    if details:
        row['details'] = details
    key = 'subscriptions' if kind == 'subscription' else 'expenses'
    data.setdefault(key, []).append(row)
    save(data, reason=f'adicionado {kind} {name}: {value:.2f}')
    label = 'assinatura' if kind == 'subscription' else 'gasto mensal'
    return f"Adicionei {name} como {label} de {_fmt_brl(value)}.\n\n{summary(data)}"


def cmd_import() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        print('Envie um JSON pelo stdin.', file=sys.stderr); return 2
    try:
        data = json.loads(raw)
    except Exception as exc:
        print(f'JSON inválido: {exc}', file=sys.stderr); return 2
    if not isinstance(data, dict):
        print('O perfil financeiro precisa ser um objeto JSON.', file=sys.stderr); return 2
    base = _empty(); base.update(data)
    save(base, reason='importação manual do perfil financeiro')
    print(summary(base)); return 0


def cmd_show() -> int:
    print(json.dumps(load(), ensure_ascii=False, indent=2)); return 0


def cmd_totals() -> int:
    print(json.dumps(totals(load()), ensure_ascii=False, indent=2)); return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('import-json'); sub.add_parser('show'); sub.add_parser('totals'); sub.add_parser('summary')
    args = parser.parse_args()
    if args.cmd == 'import-json': return cmd_import()
    if args.cmd == 'show': return cmd_show()
    if args.cmd == 'totals': return cmd_totals()
    if args.cmd == 'summary': print(summary()); return 0
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
