#!/usr/bin/env python3
"""Hermes local fast-path OpenAI-compatible proxy.

It keeps llama.cpp on the private backend port and exposes a second local endpoint
for Hermes. A tiny local classifier decides whether the latest user request can be
answered directly or needs the full Hermes agent/tool loop.

DIRECT: send only a tiny system prompt + latest user message to llama.cpp.
AGENT: keep Hermes' three bridge tools, but replace the large system prompt with a
compact local-agent contract. Tool results/continuation turns skip classification
and stay on the AGENT path.

No external provider is used. All inference stays on the same local llama.cpp model.
"""

from __future__ import annotations

import copy
import json
import os
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

ROUTER_SYSTEM = (
    "Classify the user's request for a local AI assistant. Reply exactly DIRECT if it can be "
    "answered from general model knowledge, reasoning, writing, translation, or conversation "
    "without any external/private/current state or action. Reply exactly AGENT if it needs web "
    "or current data, files, terminal/processes, code execution, browser interaction, memory or "
    "past sessions, scheduling/cron, devices/connections, image analysis/generation, or any tool. "
    "If the request depends on earlier conversation context that is not present, reply AGENT. "
    "If uncertain, reply AGENT. Output one word only."
)

DIRECT_SYSTEM = (
    "You are Hermes, a helpful local AI assistant. Answer directly in the user's language. "
    "Be accurate and concise. Do not claim current data, file access, tool use, or actions you did not perform."
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


def _latest_user(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return _content_text(msg.get("content")).strip()
    return ""


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


def _backend_json(payload: dict[str, Any], timeout: float = TIMEOUT) -> dict[str, Any]:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BACKEND + "/v1/chat/completions",
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _classify(payload: dict[str, Any], user_text: str) -> str:
    if not user_text or _depends_on_history(user_text):
        return "AGENT"
    route_payload = {
        "model": payload.get("model"),
        "messages": [
            {"role": "system", "content": ROUTER_SYSTEM},
            {"role": "user", "content": user_text},
        ],
        "stream": False,
        "max_tokens": 4,
        "temperature": 0,
    }
    result = _backend_json(route_payload, timeout=min(TIMEOUT, 120.0))
    try:
        text = result["choices"][0]["message"]["content"].strip().upper()
    except Exception:
        return "AGENT"
    return "DIRECT" if text.startswith("DIRECT") else "AGENT"


def _direct_payload(payload: dict[str, Any], user_text: str) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    out["messages"] = [
        {"role": "system", "content": DIRECT_SYSTEM},
        {"role": "user", "content": user_text},
    ]
    out.pop("tools", None)
    out.pop("tool_choice", None)
    out.pop("parallel_tool_calls", None)
    return out


def _agent_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(payload)
    messages = [m for m in (out.get("messages") or []) if isinstance(m, dict) and m.get("role") != "system"]
    out["messages"] = [{"role": "system", "content": AGENT_SYSTEM}, *messages]
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "HermesFastRouter/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stdout.write("[fast-router] " + (fmt % args) + "\n")
        sys.stdout.flush()

    def _relay(self, url: str, body: bytes | None = None, content_type: str | None = None) -> None:
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
        try:
            resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as exc:
            data = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
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
                self.wfile.write(data)
            else:
                self.end_headers()
                while True:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            self.close_connection = True

    def do_GET(self) -> None:
        if self.path == "/health":
            data = json.dumps({"ok": True, "backend": BACKEND}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
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

        # No Hermes tool surface: this is already a compact/direct request (auxiliary tasks,
        # smoke tests, or callers using the endpoint directly). Proxy unchanged.
        if not tools:
            self.log_message("route=PASSTHROUGH no-tools")
            self._relay(BACKEND + self.path, raw, "application/json")
            return

        # After a tool call we must preserve the agent loop. Do not classify again.
        if _is_continuation(messages):
            routed = _agent_payload(payload)
            self.log_message("route=AGENT continuation compact-system")
            self._relay(BACKEND + self.path, json.dumps(routed, ensure_ascii=False).encode(), "application/json")
            return

        user_text = _latest_user(messages)
        try:
            route = _classify(payload, user_text)
        except Exception as exc:
            route = "AGENT"
            self.log_message("classifier-error=%r fallback=AGENT", exc)

        elapsed_ms = int((time.monotonic() - started) * 1000)
        if route == "DIRECT":
            routed = _direct_payload(payload, user_text)
            self.log_message("route=DIRECT classify_ms=%d chars=%d", elapsed_ms, len(user_text))
        else:
            routed = _agent_payload(payload)
            self.log_message("route=AGENT classify_ms=%d compact-system chars=%d", elapsed_ms, len(user_text))

        self._relay(BACKEND + self.path, json.dumps(routed, ensure_ascii=False).encode(), "application/json")


def main() -> int:
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(f"[fast-router] listening=http://{LISTEN_HOST}:{LISTEN_PORT} backend={BACKEND}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
