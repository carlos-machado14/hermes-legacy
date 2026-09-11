#!/usr/bin/env python3
"""Hermes Fast Router v6.

Adds a deterministic pre-dispatch path for simple, known agent actions. Instead of
asking the local 4B model to manufacture a tool_call, the proxy returns a normal
OpenAI-compatible tool_call response directly. Hermes still executes the tool via
its own tool dispatcher; only the expensive first LLM round-trip is skipped.

The v5 router remains the base implementation for DIRECT routing, continuation
compaction, and all generic/unknown agent requests.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import hermes_fast_router as base


_HOSTNAME_RE = re.compile(r"\bhostname\b", re.IGNORECASE)


def _tool_names(tools: Any) -> set[str]:
    names: set[str] = set()
    if not isinstance(tools, list):
        return names
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else {}
        name = str(fn.get("name") or "").strip()
        if name:
            names.add(name)
    return names


def _fast_tool_plan(user_text: str, tools: Any) -> dict[str, Any] | None:
    """Return a safe deterministic plan only when the exact bridge is available.

    Keep this intentionally conservative. We only skip model planning for operations
    whose command is fully fixed by the intent; arbitrary shell text from the user is
    never copied into a command here.
    """
    if "tool_call" not in _tool_names(tools):
        return None
    if _HOSTNAME_RE.search(user_text):
        return {
            "bridge": "tool_call",
            "underlying": "terminal",
            "arguments": {"command": "hostname"},
            "recipe": "hostname",
        }
    return None


class Handler(base.Handler):
    server_version = "HermesFastRouter/6.0"

    def _send_tool_call(self, payload: dict[str, Any], plan: dict[str, Any]) -> None:
        """Emit a synthetic OpenAI-compatible assistant tool call.

        Supports both non-streaming and SSE streaming callers. Hermes receives this
        exactly like a provider-generated tool call and therefore executes it through
        its normal tool safety/dispatch path.
        """
        created = int(time.time())
        stamp = int(time.time() * 1000)
        response_id = f"chatcmpl-hermes-fast-{stamp}"
        call_id = f"call_hermes_fast_{stamp}"
        model = str(payload.get("model") or "local")
        bridge_args = {
            "calls": [
                {
                    "name": plan["underlying"],
                    "arguments": plan["arguments"],
                }
            ]
        }
        args_json = json.dumps(bridge_args, ensure_ascii=False, separators=(",", ":"))
        tool_call = {
            "id": call_id,
            "type": "function",
            "function": {
                "name": plan["bridge"],
                "arguments": args_json,
            },
        }

        if bool(payload.get("stream")):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            first = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": plan["bridge"],
                                        "arguments": args_json,
                                    },
                                }
                            ],
                        },
                        "finish_reason": None,
                    }
                ],
            }
            final = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "tool_calls",
                    }
                ],
            }
            self._safe_write(("data: " + json.dumps(first, ensure_ascii=False) + "\n\n").encode())
            self._safe_write(("data: " + json.dumps(final, ensure_ascii=False) + "\n\n").encode())
            self._safe_write(b"data: [DONE]\n\n")
            self.close_connection = True
            return

        body = {
            "id": response_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [tool_call],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }
        self._json_response(200, body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json_response(200, {"ok": True, "backend": base.BACKEND, "router_version": 6})
            return
        self._relay(base.BACKEND + self.path)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            self._json_response(400, {"error": "invalid JSON"})
            return

        if self.path in {"/route", "/v1/route"}:
            text = str(payload.get("text") or payload.get("prompt") or "").strip()
            messages = [{"role": "user", "content": text}]
            route, reason = base._route_heuristic(messages, text)
            self.log_message("route-probe=%s reason=%s chars=%d", route, reason, len(text))
            self._json_response(200, {"route": route, "reason": reason, "router_version": 6})
            return

        if self.path != "/v1/chat/completions":
            self._relay(base.BACKEND + self.path, raw, self.headers.get("Content-Type", "application/json"))
            return

        messages = payload.get("messages") or []
        tools = payload.get("tools") or []
        started = time.monotonic()

        if not tools:
            self.log_message("route=PASSTHROUGH no-tools")
            self._relay(base.BACKEND + self.path, raw, "application/json")
            return

        user_text = base._latest_user(messages)
        if base._is_continuation(messages):
            routed = base._agent_payload(payload, user_text)
            mode = "post-tool-compact" if base._has_real_tool_call(messages) else "bridge-continuation"
            self.log_message("route=AGENT reason=continuation mode=%s chars=%d", mode, len(user_text))
            self._relay(
                base.BACKEND + self.path,
                json.dumps(routed, ensure_ascii=False).encode(),
                "application/json",
            )
            return

        route, reason = base._route_heuristic(messages, user_text)
        elapsed_ms = int((time.monotonic() - started) * 1000)

        if route == "DIRECT":
            routed = base._direct_payload(payload, user_text)
            self.log_message("route=DIRECT reason=%s route_ms=%d chars=%d", reason, elapsed_ms, len(user_text))
            self._relay(
                base.BACKEND + self.path,
                json.dumps(routed, ensure_ascii=False).encode(),
                "application/json",
            )
            return

        plan = _fast_tool_plan(user_text, tools)
        if plan is not None:
            self.log_message(
                "route=AGENT reason=%s route_ms=%d fast_dispatch=synthetic-tool-call recipe=%s tool=%s chars=%d",
                reason,
                elapsed_ms,
                plan["recipe"],
                plan["underlying"],
                len(user_text),
            )
            self._send_tool_call(payload, plan)
            return

        routed = base._agent_payload(payload, user_text)
        self.log_message(
            "route=AGENT reason=%s route_ms=%d fast_dispatch=none chars=%d",
            reason,
            elapsed_ms,
            len(user_text),
        )
        self._relay(
            base.BACKEND + self.path,
            json.dumps(routed, ensure_ascii=False).encode(),
            "application/json",
        )


def main() -> int:
    server = base.ThreadingHTTPServer((base.LISTEN_HOST, base.LISTEN_PORT), Handler)
    print(
        f"[fast-router] version=6 listening=http://{base.LISTEN_HOST}:{base.LISTEN_PORT} backend={base.BACKEND}",
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
