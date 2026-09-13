#!/usr/bin/env python3
"""Hermes Fast Router v9.

Extends v8 with deterministic host-side dispatch to Hermes Core v2.1 for
operational requests (health, recovery, memory, tools and safe restarts).
Cron management remains on the v8 fastpath. Ordinary chat still falls through
to the local model backend.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import hermes_fast_router as base
import hermes_fast_router_v7 as v7
import hermes_fast_router_v8 as v8

_ORIGINAL_ROUTE = base._route_heuristic
_ORIGINAL_PROBE = v7._safe_host_probe
_CORE_PREFIX = "HERMES_CORE_RESULT:"

_CORE_INTENT_RE = re.compile(
    r"(?:\b(?:status|sa[uú]de|health)\b.*\b(?:vps|hermes|servi[cç]os?)\b|"
    r"\b(?:verifique|verificar)\b.*\b(?:vps|servi[cç]os?|crons?)\b|"
    r"\b(?:corrija tudo|corrigir tudo|recupere os servi[cç]os|auto[- ]?recovery)\b|"
    r"\b(?:o que (?:voc[eê] )?corrigiu|hist[oó]rico (?:operacional|de corre[cç][oõ]es))\b|"
    r"\b(?:reinicie|reiniciar)\b.*\b(?:gateway|router|llm|modelo|health|monitor)\b|"
    r"\b(?:quais ferramentas|listar ferramentas|ferramentas)\b|"
    r"\b(?:containers|docker ps|status do docker)\b|"
    r"\b(?:logs? do (?:gateway|llm|modelo|router))\b)",
    re.IGNORECASE,
)


def _is_core_intent(text: str) -> bool:
    return bool(_CORE_INTENT_RE.search(text or ""))


def _route_heuristic(messages: Any, user_text: str):
    if _is_core_intent(user_text):
        return "AGENT", "core-v21-fastpath"
    return _ORIGINAL_ROUTE(messages, user_text)


def _run_core(user_text: str) -> str:
    root = Path.home() / '.hermes' / 'core-v2'
    py = root / 'venv' / 'bin' / 'python'
    core = root / 'hermes_core.py'
    if not py.exists() or not core.exists():
        return '⚠️ Hermes Core v2.1 ainda não está instalado. Rode ./install-core-v2.sh na VPS.'
    try:
        proc = subprocess.run(
            [str(py), str(core), user_text],
            text=True,
            capture_output=True,
            timeout=150,
            cwd=str(root),
        )
    except subprocess.TimeoutExpired:
        return '⚠️ Hermes Core excedeu o tempo limite desta ação.'
    except Exception as exc:
        return f'⚠️ Falha ao executar Hermes Core: {exc}'
    output = (proc.stdout or '').strip()
    error = (proc.stderr or '').strip()
    if proc.returncode != 0:
        return f'⚠️ Hermes Core retornou erro: {(error or output)[-700:]}'
    return output or 'Hermes Core concluiu a ação sem mensagem de retorno.'


def _safe_host_probe(user_text: str) -> tuple[str, str] | None:
    # Keep cron v8 behavior first: requests about cron creation/lifecycle must not
    # be swallowed by the broader operational regex.
    if v8._is_cron_intent(user_text):
        return _ORIGINAL_PROBE(user_text)
    if _is_core_intent(user_text):
        return 'core-v21-host', _run_core(user_text)
    return _ORIGINAL_PROBE(user_text)


base._route_heuristic = _route_heuristic
v7._safe_host_probe = _safe_host_probe


class Handler(v8.Handler):
    server_version = 'HermesFastRouter/9.0'

    def do_GET(self) -> None:
        if self.path == '/health':
            self._json_response(200, {'ok': True, 'backend': base.BACKEND, 'router_version': 9, 'core_fastpath': True})
            return
        super().do_GET()


def main() -> int:
    server = base.ThreadingHTTPServer((base.LISTEN_HOST, base.LISTEN_PORT), Handler)
    print(f'[fast-router] version=9 listening=http://{base.LISTEN_HOST}:{base.LISTEN_PORT} backend={base.BACKEND}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
