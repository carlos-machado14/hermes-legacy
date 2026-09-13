#!/usr/bin/env python3
"""Hermes Fast Router v8.

Adds deterministic Portuguese cron-management dispatch for Telegram/chat on top
of v7. Cron lifecycle requests execute directly on the VPS host, avoiding the
isolated terminal tool and avoiding another LLM turn.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import hermes_fast_router as base
import hermes_fast_router_v7 as v7

_ORIGINAL_ROUTE = base._route_heuristic
_ORIGINAL_PROBE = v7._safe_host_probe
_ORIGINAL_PLAN = v7._fast_tool_plan
_ORIGINAL_FINAL = v7._strict_fast_final
_RESULT_PREFIX = "HERMES_CRON_RESULT:"

_CRON_INTENT_RE = re.compile(
    r"(?:\b(?:crie|criar|adicione|adicionar|agende|agendar|pause|pausar|pare|parar|"
    r"retome|retomar|remova|remover|apague|apagar|rode|rodar|execute|executar)\b.*"
    r"\b(?:rotina|cron|lembrete|todo dia|todos os dias|diariamente|a cada|not[ií]cias?)\b|"
    r"\b(?:me lembre|lembre-me)\b|"
    r"\b(?:todo dia|todos os dias|diariamente|a cada\s+\d+\s+(?:minutos?|horas?|dias?))\b.*"
    r"\b(?:mande|envie|avise|lembre|not[ií]cias?)\b|"
    r"\b(?:quais rotinas|minhas rotinas|listar rotinas|liste as rotinas|listar crons)\b)",
    re.IGNORECASE,
)


def _is_cron_intent(text: str) -> bool:
    return bool(_CRON_INTENT_RE.search(text or ""))


def _route_heuristic(messages: Any, user_text: str):
    if _is_cron_intent(user_text):
        return "AGENT", "cron-manager-fastpath"
    return _ORIGINAL_ROUTE(messages, user_text)


def _find_cron_result(value: Any, depth: int = 0) -> str | None:
    if depth > 6:
        return None
    if isinstance(value, str):
        if _RESULT_PREFIX in value:
            return value.rsplit(_RESULT_PREFIX, 1)[-1].strip()
        if value[:1] in {"{", "[", '"'}:
            try:
                return _find_cron_result(json.loads(value), depth + 1)
            except Exception:
                return None
        return None
    if isinstance(value, dict):
        for item in value.values():
            found = _find_cron_result(item, depth + 1)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_cron_result(item, depth + 1)
            if found:
                return found
    return None


def _run_cron_manager(user_text: str) -> str:
    manager = Path.home() / ".hermes" / "core-v2" / "cron_manager.py"
    if not manager.exists():
        return "⚠️ Cron Manager local ainda não está instalado. Rode install-cron-manager.sh na VPS."
    encoded = base64.urlsafe_b64encode(user_text.encode("utf-8")).decode("ascii")
    try:
        proc = subprocess.run(
            [sys.executable, str(manager), "--text-b64", encoded],
            text=True,
            capture_output=True,
            timeout=35,
        )
    except Exception as exc:
        return f"⚠️ Falha ao executar o Cron Manager local: {exc}"
    raw = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    result = _find_cron_result(raw)
    if result:
        return result
    if proc.returncode != 0:
        return f"⚠️ Cron Manager retornou erro: {raw[-600:].strip()}"
    return raw.strip() or "⚠️ Cron Manager não retornou resposta."


def _safe_host_probe(user_text: str) -> tuple[str, str] | None:
    if _is_cron_intent(user_text):
        return "cron-manager-host", _run_cron_manager(user_text)
    return _ORIGINAL_PROBE(user_text)


def _fast_tool_plan(user_text: str, tools: Any) -> dict[str, Any] | None:
    # Cron management is handled directly by _safe_host_probe on the VPS host.
    return _ORIGINAL_PLAN(user_text, tools)


def _strict_fast_final(messages: Any, user_text: str) -> str | None:
    tool_text = v7._latest_tool_text(messages)
    if tool_text:
        try:
            parsed: Any = json.loads(tool_text)
        except Exception:
            parsed = tool_text
        result = _find_cron_result(parsed)
        if result:
            return result
    return _ORIGINAL_FINAL(messages, user_text)


base._route_heuristic = _route_heuristic
v7._safe_host_probe = _safe_host_probe
v7._fast_tool_plan = _fast_tool_plan
v7._strict_fast_final = _strict_fast_final


class Handler(v7.Handler):
    server_version = "HermesFastRouter/8.0"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json_response(200, {"ok": True, "backend": base.BACKEND, "router_version": 8})
            return
        super().do_GET()


def main() -> int:
    server = base.ThreadingHTTPServer((base.LISTEN_HOST, base.LISTEN_PORT), Handler)
    print(
        f"[fast-router] version=8 listening=http://{base.LISTEN_HOST}:{base.LISTEN_PORT} backend={base.BACKEND}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
