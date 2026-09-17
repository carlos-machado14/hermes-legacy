#!/usr/bin/env python3
from __future__ import annotations

import json
import time

from semantic_provider import classify, health

CASES = [
    'cancela todos meus compromissos da agenda vamos resetar ela',
    'qual minha agenda para sábado',
    'me lembra amanhã às 10h de revisar o Hermes',
]

print(json.dumps(health(), ensure_ascii=False, indent=2))
for text in CASES:
    started = time.perf_counter()
    try:
        out = classify(text, '')
        print(f'\n{text}\n=> {out}')
    except Exception as exc:
        print(f'\n{text}\n=> ERROR: {type(exc).__name__}: {exc}')
    finally:
        print(f'elapsed={time.perf_counter() - started:.3f}s')
