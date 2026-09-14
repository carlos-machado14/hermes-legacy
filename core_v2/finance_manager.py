#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

STATE = Path.home() / '.hermes' / 'core-v2' / 'state'
PROFILE = STATE / 'finance_profile.json'


def load() -> dict[str, Any]:
    if not PROFILE.exists():
        return {'version': 1, 'income': {}, 'expenses': [], 'subscription_groups': [], 'notes': []}
    try:
        data = json.loads(PROFILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save(data: dict[str, Any]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    data['version'] = int(data.get('version') or 1)
    data['updated_at'] = datetime.now().astimezone().isoformat()
    tmp = PROFILE.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(PROFILE)


def _money(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def totals(data: dict[str, Any]) -> dict[str, float]:
    expenses = [x for x in data.get('expenses', []) if isinstance(x, dict) and x.get('active', True)]
    groups = [x for x in data.get('subscription_groups', []) if isinstance(x, dict) and x.get('active', True)]
    expense_total = sum(_money(x.get('monthly_value')) for x in expenses)
    subscriptions_total = sum(_money(x.get('monthly_total')) for x in groups)
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


def cmd_import() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        print('Envie um JSON pelo stdin.', file=sys.stderr)
        return 2
    try:
        data = json.loads(raw)
    except Exception as exc:
        print(f'JSON inválido: {exc}', file=sys.stderr)
        return 2
    if not isinstance(data, dict):
        print('O perfil financeiro precisa ser um objeto JSON.', file=sys.stderr)
        return 2
    save(data)
    t = totals(data)
    print(f'Perfil financeiro salvo em {PROFILE}')
    print(f"Total fixo mensal: R$ {t['total']:.2f}")
    if t['income']:
        print(f"Renda mensal: R$ {t['income']:.2f}")
        print(f"Comprometimento: {t['commitment_pct']:.1f}%")
        print(f"Livre após fixos informados: R$ {t['free_after_fixed']:.2f}")
    return 0


def cmd_show() -> int:
    data = load()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_totals() -> int:
    print(json.dumps(totals(load()), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('import-json')
    sub.add_parser('show')
    sub.add_parser('totals')
    args = parser.parse_args()
    if args.cmd == 'import-json': return cmd_import()
    if args.cmd == 'show': return cmd_show()
    if args.cmd == 'totals': return cmd_totals()
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
