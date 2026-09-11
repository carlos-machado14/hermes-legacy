#!/usr/bin/env python3
"""Hermes local fast-path OpenAI-compatible proxy.

The proxy keeps llama.cpp private on the backend port and exposes a second local
endpoint for Hermes. Requests that clearly do not need tools take a minimal DIRECT
path; requests that need current/private state or actions keep the Hermes agent path.

Routing is deterministic by default. On a small CPU VPS an LLM classifier costs an
extra generation before every answer, so using the same 4B model just to decide
DIRECT vs AGENT defeats the purpose of the fast path.

DIRECT: tiny system prompt + latest user message, no tools.
AGENT: compact local-agent contract + Hermes' progressive-disclosure bridge tools.
Tool continuations always stay on AGENT.

All inference remains local on the same llama.cpp runtime.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

LISTEN_HOST = os.getenv("HERMES_FAST_ROUTER_HOST", "127.0.0.1")
LISTEN_PORT = int(os.getenv("HERMES_FAST_ROUTER_PORT", "8089"))
BACKEND = os.getenv("HERMES_FAST_ROUTER_BACKEND", "http://127.0.0.1:8088").rstrip("/")
TIMEOUT = float(os.getenv("HERMES_FAST_ROUTER_TIMEOUT", "1800"))

# Keep the cached prefix intentionally tiny. The user's own request carries the
# desired language/style; repeated direct turns should reuse this prefix in llama.cpp.
DIRECT_SYSTEM = (
    "You are Hermes. Answer accurately and concisely in the user's language. "
    "Follow requested output format exactly. Never invent current data, tool use, or actions."
)

AGENT_SYSTEM = (
    "You are Hermes, a local agent. Answer in the user's language. Use a tool only when the request "
    "needs external/private/current state or an action. Deferred capability families available through "
    "tool_search include: web/current information; files; terminal/processes; code execution; memory and "
    "past sessions; skills; cron/scheduling; browser; vision/images; todo; delegation; connections; clarify. "
    "For a deferred capability use tool_search, then tool_describe when parameters are unknown, then tool_call. "
    "Never fabricate tool results or actions. If no tool is needed, answer directly. Keep calls and final answers concise."
)

_CONTEXTUAL_HINTS = (
    "isso", "isto", "aquilo", "esse", "essa", "esses", "essas", "anterior", "antes", "acima",
    "como falei", "como disse", "como combinamos", "continue", "continua", "de novo", "o mesmo",
    "that", "this", "previous", "above", "as i said", "continue", "same one",
)

_CURRENT_RE = re.compile(
    r"\b(hoje|agora|atual(?:mente)?|recent(?:e|es|emente)?|últim[oa]s?|ultim[oa]s?|"
    r"latest|today|current|now|weather|clima|previs[aã]o do tempo|d[oó]lar|euro|cota[cç][aã]o|"
    r"c[aâ]mbio|not[ií]cias?|news|placar|score|tr[aâ]nsito|traffic|pre[cç]o atual|valor atual|"
    r"disponibilidade|availability|status do voo|flight status)\b",
    re.IGNORECASE,
)

_ACTION_RE = re.compile(
    r"\b(pesquis(?:e|ar)|busqu(?:e|ar)|procure|consulte|acesse|abra|abrir|clique|clicar|"
    r"execute|executar|rode|rodar|edite|editar|altere|alterar|modifique|modificar|"
    r"leia|ler|salve|salvar|grave|gravar|baixe|baixar|fa[cç]a upload|upload|download|"
    r"agende|agendar|lembre|lembrar|crie um lembrete|criar um lembrete|"
    r"envie|enviar|mande|mandar|use (?:uma |a )?ferramenta|use tool|"
    r"search|browse|open|click|run|execute|read|write|edit|save|schedule|remind|send)\b",
    re.IGNORECASE,
)

_CAPABILITY_RE = re.compile(
    r"\b(web|internet|google|site|url|arquivo|arquivos|file|files|pasta|folder|terminal|shell|"
    r"processo|process|hostname|servidor|server|vps|docker|github|repo|reposit[oó]rio|"
    r"mem[oó]ria|memory|sess[aã]o|session|cron|agenda|calendar|browser|navegador|"
    r"imagem|image|foto|photo|screenshot|email|e-mail|drive|conex[aã]o|connection|"
    r"dispositivo|device|banco de dados|database|db)\b",
    re.IGNORECASE,
)

_PRIVATE_POSSESSIVE_RE = re.compile(
    r"\b(meu|minha|meus|minhas|my)\b.{0,40}\b(arquivo|file|projeto|project|repo|reposit[oó]rio|"
    r"servidor|server|vps|configura[cç][aã]o|config|email|drive|agenda|calendar|"
    r"mem[oó]ria|memory|conversa|chat|sess[aã]o|session)\b",
    re.IGNORECASE | re.DOTALL,
)

_STRICT_OUTPUT_RE = re.compile(
    r"\b(somente|apenas|s[oó]|only|just|one word|uma palavra|sem explica[cç][aã]o|"
    r"sem texto extra|no explanation|nothing else)\b",
    re.IGNORECASE,
)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") in {"text", "input_text"} and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "\n".join(parts)
    return str(content or "")


def _latest_user_message(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg
    return None


def _latest_user(messages: list[dict[str, Any]]) -> str:
    msg = _latest_user_message(messages)
    return _content_text(msg.get("content")).strip() if msg else ""


def _has_non_text_user_content(messages: list[dict[str, Any]]) -> bool:
    msg = _latest_user_message(messages)
    if not msg:
        return False
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    for item in content:
        if not isinstance(item, dict):
            return True
        if item.get("type") not in {"text", "input_text"}:
            return True
    return False


def _is_continuation(messages: list[dict[str, Any]]) -> bool:
    for msg in messages:
        if msg.get("role") == "tool":
            return True
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            return True
    return False


def _depends_on_history(text: str) -> bool:
    lower = text.lower()
    return any(hint in lower for hint in _CONTEXTUAL_HINTS)


def _route_heuristic(messages: list[dict[str, Any]], user_text: str) -> tuple[str, str]:
    if not user_text:
        return "AGENT", "empty-user"
    if _has_non_text_user_content(messages):
        return "AGENT", "non-text-input"
    if _depends_on_history(user_text):
        return "AGENT", "history-reference"
    if _CURRENT_RE.search(user_text):
        return "AGENT", "current-state"
    if _PRIVATE_POSSESSIVE_RE.search(user_text):
        return "AGENT", "private-state"
    if _ACTION_RE.search(user_text) and _CAPABILITY_RE.search(user_text):
        return "AGENT", "external-action"
    return "DIRECT", "knowledge"


def _direct_payload(payload: dict[str, Any], user_text: str) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    out["messages"] = [
        {"role": "system", "content": DIRECT_SYSTEM},
        {"role": "user", "content": user_text},
    ]
    out.pop("tools", None)
    out.pop("tool_choice", None)
    out.pop("parallel_tool_calls", None)

    # Prevent a CPU-local model from turning a simple direct question into a
    # long monologue. Normal DIRECT answers are bounded; explicit short-format
    # requests get an even tighter cap.
    current = out.get("max_tokens")
    if not isinstance(current, int) or current <= 0:
        current = 128
    out["max_tokens"] = min(current, 128)
    if _STRICT_OUTPUT_RE.search(user_text):
        out["max_tokens"] = min(out["max_tokens"], 12)
        out["temperature"] = 0
    return out


def _agent_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    messages = [m for m in (out.get("messages") or []) if isinstance(m, dict) and m.get("role") != "system"]
    out["messages"] = [{"role": "system", "content": AGENT_SYSTEM}, *messages]
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "HermesFastRouter/3.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stdout.write("[fast-router] " + (fmt % args) + "\n")
        sys.stdout.flush()

    def _safe_write(self, data: bytes) -> bool:
        try:
            self.wfile.write(data)
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError):
            # Common when `timeout`, Ctrl-C, or a short-lived oneshot process
            # closes its side after the useful foreground answer completed.
            self.close_connection = True
            return False

    def _relay(self, url: str, body: bytes | None = None, content_type: str | None = None) -> None:
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
        upstream_started = time.monotonic()
        try:
            resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as exc:
            data = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self._safe_write(data)
            return
        with resp:
            ctype = resp.headers.get("Content-Type", "application/json")
            is_stream = "text/event-stream" in ctype
            self.send_response(resp.status)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            if not is_stream:
                data = resp.read()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self._safe_write(data)
            else:
                self.end_headers()
                while True:
                    chunk = resp.read(4096)
                    if not chunk or not self._safe_write(chunk):
                        break
            self.close_connection = True
        self.log_message("upstream_ms=%d", int((time.monotonic() - upstream_started) * 1000))

    def do_GET(self) -> None:
        if self.path == "/health":
            data = json.dumps({"ok": True, "backend": BACKEND, "router_version": 3}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self._safe_write(data)
            return
        self._relay(BACKEND + self.path)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length)
        if self.path != "/v1/chat/completions":
            self._relay(BACKEND + self.path, raw, self.headers.get("Content-Type", "application/json"))
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self.send_error(400, "invalid JSON")
            return

        messages = payload.get("messages") or []
        tools = payload.get("tools") or []
        started = time.monotonic()

        if not tools:
            self.log_message("route=PASSTHROUGH no-tools")
            self._relay(BACKEND + self.path, raw, "application/json")
            return

        if _is_continuation(messages):
            routed = _agent_payload(payload)
            self.log_message("route=AGENT reason=continuation compact-system")
            self._relay(BACKEND + self.path, json.dumps(routed, ensure_ascii=False).encode(), "application/json")
            return

        user_text = _latest_user(messages)
        route, reason = _route_heuristic(messages, user_text)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if route == "DIRECT":
            routed = _direct_payload(payload, user_text)
            self.log_message("route=DIRECT reason=%s route_ms=%d chars=%d", reason, elapsed_ms, len(user_text))
        else:
            routed = _agent_payload(payload)
            self.log_message("route=AGENT reason=%s route_ms=%d compact-system chars=%d", reason, elapsed_ms, len(user_text))

        self._relay(BACKEND + self.path, json.dumps(routed, ensure_ascii=False).encode(), "application/json")


def main() -> int:
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(f"[fast-router] version=3 listening=http://{LISTEN_HOST}:{LISTEN_PORT} backend={BACKEND}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
