#!/usr/bin/env python3
"""Hermes Fast Router v8.

Adds deterministic Portuguese cron-management dispatch for Telegram/chat on top
of v7. Cron lifecycle requests are sent to the local Core v2 cron manager and
its tool result is finalized without another LLM turn.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Any

import hermes_fast_router as base
import hermes_fast_router_v7 as v7

_ORIGINAL_ROUTE = base._route_heuristic
_ORIGINAL_PLAN = v7._fast_tool_plan
_ORIGINAL_FINAL = v7._strict_fast_final
_RESULT_PREFIX = "HERMES_CRON_RESULT:"

_CRON_INTENT_RE = re.compile(
    r"(?:\b(?:crie|criar|adicione|adicionar|agende|agendar|pause|pausar|pare|parar|"
    r"retome|retomar|remova|remover|apague|apagar|rode|rodar|execute|executar)\b.*"
    r"\b(?:rotina|cron|lembrete|todo dia|todos os dias|diariamente|a cada|not[ií]cias?)\b|"
    r"\b(?:me lembre|lembre-me)\b|"
    r"\b(?:quais rotinas|minhas rotinas|listar rotinas|liste as rotinas|listar crons)\b)",
    re.IGNORECASE,
)


def _is_cron_intent(text: str) -> bool:
    return bool(_CRON_INTENT_RE.search(text or ""))


def _route_heuristic(messages: Any, user_text: str):
    if _is_cron_intent(user_text):
        return "AGENT", "cron-manager-fastpath"
    return _ORIGINAL_ROUTE(messages, user_text)


def _cron_tool_plan(user_text: str, tools: Any) -> dict[str, Any] | None:
    if not _is_cron_intent(user_text):
        return None
    if "tool_call" not in v7._tool_names(tools):
        return None
    encoded = base64.urlsafe_b64encode(user_text.encode("utf-8")).decode("ascii")
    command = (
        "$HOME/.hermes/core-v2/venv/bin/python "
        "$HOME/.hermes/core-v2/cron_manager.py --text-b64 " + encoded
    )
    return {
        "bridge": "tool_call",
        "underlying": "terminal",
        "arguments": {"command": command},
        "recipe": "cron-manager-local",
    }


def _fast_tool_plan(user_text: str, tools: Any) -> dict[str, Any] | None:
    plan = _cron_tool_plan(user_text, tools)
    if plan is not None:
        return plan
    return _ORIGINAL_PLAN(user_text, tools)


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


# v7's Handler resolves these module globals at runtime; patching them keeps the
# proven v7 request flow while adding the new deterministic fast path.
base._route_heuristic = _route_heuristic
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
