#!/usr/bin/env python3
from __future__ import annotations

import json
import time

from semantic_provider import health, llm

SYSTEM = '/no_think\nRetorne somente JSON válido.'
PROMPT = 'Mensagem: cancele todos os meus lembretes de hoje\nJSON: {"action":"remove","entity":"reminder","scope":"all","period":"today"}'

print(json.dumps(health(), ensure_ascii=False, indent=2))
started = time.perf_counter()
try:
    out = llm(PROMPT, system=SYSTEM, max_tokens=64)
    print(out)
except Exception as exc:
    print(f'ERROR: {type(exc).__name__}: {exc}')
finally:
    print(f'elapsed={time.perf_counter() - started:.3f}s')
