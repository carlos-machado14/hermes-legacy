#!/usr/bin/env python3
from __future__ import annotations

import json
import time

from semantic_provider import classify, health

CASES = [
    ('quais sao minhas rotinas', 'L|R|A|Q|U'),
    ('cancela todos meus compromissos da agenda vamos resetar ela', 'R|S|A|A|T'),
    ('qual minha agenda para sábado', 'L|A|F|Q|T'),
    ('me lembra amanhã às 10h de revisar o Hermes', 'C|M|1|A|T'),
]

print(json.dumps(health(), ensure_ascii=False, indent=2))
passed = 0
for text, expected in CASES:
    started = time.perf_counter()
    try:
        out = classify(text, '')
        ok = out == expected
        passed += int(ok)
        status = 'PASS' if ok else f'FAIL expected={expected}'
        print(f'\n{text}\n=> {out}  [{status}]')
    except Exception as exc:
        print(f'\n{text}\n=> ERROR: {type(exc).__name__}: {exc}  [FAIL expected={expected}]')
    finally:
        print(f'elapsed={time.perf_counter() - started:.3f}s')

print(f'\nRESULTADO: {passed}/{len(CASES)}')
raise SystemExit(0 if passed == len(CASES) else 2)
