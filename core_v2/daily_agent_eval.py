#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time

from conversation_brain import decide
from daily_agent_examples import EXAMPLES
from semantic_provider import health, llm

FIELDS = ('mode', 'route', 'action')
TARGET_FIELDS = ('entity', 'scope')


def expected(item: dict) -> dict:
    return item['o']


def actual_flat(result: dict | None) -> dict:
    if not result:
        return {}
    target = result.get('target') if isinstance(result.get('target'), dict) else {}
    return {
        'mode': result.get('mode'),
        'route': result.get('route'),
        'action': result.get('action'),
        'entity': target.get('entity'),
        'scope': target.get('scope'),
    }


def matches(exp: dict, got: dict) -> tuple[bool, list[str]]:
    wrong: list[str] = []
    for field in FIELDS + TARGET_FIELDS:
        if field in exp and exp[field] != got.get(field):
            wrong.append(field)
    return not wrong, wrong


def main() -> int:
    parser = argparse.ArgumentParser(description='Avalia o Daily Agent sem executar ações.')
    parser.add_argument('--full', action='store_true', help='Executa todo o corpus de linguagem diária.')
    parser.add_argument('--limit', type=int, default=16, help='Quantidade no smoke test.')
    args = parser.parse_args()

    corpus = EXAMPLES if args.full else EXAMPLES[:max(1, min(args.limit, len(EXAMPLES)))]
    print(json.dumps(health(), ensure_ascii=False, indent=2))
    print(f'\nCasos: {len(corpus)} | modo: {"full" if args.full else "smoke"}\n')

    passed = 0
    started_all = time.perf_counter()
    for idx, item in enumerate(corpus, 1):
        started = time.perf_counter()
        result = decide(item['u'], '', llm)
        elapsed = time.perf_counter() - started
        got = actual_flat(result)
        ok, wrong = matches(expected(item), got)
        passed += int(ok)
        marker = 'OK' if ok else 'FAIL'
        print(f'[{marker}] {idx:02d} {elapsed:5.2f}s | {item["u"]}')
        if not ok:
            print('  esperado:', json.dumps(expected(item), ensure_ascii=False, separators=(',', ':')))
            print('  recebido:', json.dumps(got, ensure_ascii=False, separators=(',', ':')))
            print('  divergências:', ', '.join(wrong) or 'sem resposta')

    total_elapsed = time.perf_counter() - started_all
    pct = (passed / len(corpus) * 100) if corpus else 0
    print(f'\nResultado: {passed}/{len(corpus)} ({pct:.1f}%) em {total_elapsed:.2f}s')
    # Smoke test only blocks installation for severe regressions. The full corpus is diagnostic.
    if not args.full and pct < 75:
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
