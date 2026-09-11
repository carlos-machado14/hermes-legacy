#!/usr/bin/env python3
"""Hermes Fast Router v7.

Builds on v6 with two CPU-VPS optimizations:

1. Safe host probes for deterministic read-only facts (currently the VPS hostname)
   are answered by the router process itself. This avoids Hermes' isolated terminal
   environment returning container/sandbox values such as ``localhost``.
2. Strict-output continuations can be finalized directly from a short tool result,
   avoiding one or more extra LLM turns after the useful tool already ran.

Unknown or non-trivial agent work still falls through to Hermes + Qwen normally.
"""

from __future__ import annotations

import json
import re
import socket
import time
from typing import Any

import hermes_fast_router as base


_HOSTNAME_RE = re.compile(r"\bhostname\b", re.IGNORECASE)
_LOCAL_MACHINE_RE = re.compile(
    r"\b(desta m[aá]quina|deste servidor|desta vps|local machine|this machine|this server|this vps)\b",
    re.IGNORECASE,
)


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


def _safe_host_probe(user_text: str) -> tuple[str, str] | None:
    """Return (recipe, value) for exact read-only host facts.

    The fast-router service itself runs on the VPS host as the Hermes user, while
    Hermes' terminal tool may intentionally run inside an isolated environment.
    Only fixed, non-user-controlled host probes belong here.
    """
    if _HOSTNAME_RE.search(user_text) and _LOCAL_MACHINE_RE.search(user_text):
        return "host-hostname", socket.gethostname().strip()
    return None


def _fast_tool_plan(user_text: str, tools: Any) -> dict[str, Any] | None:
    """Return a safe deterministic Hermes tool plan when appropriate.

    Keep arbitrary user shell text out of this path. Host-level hostname requests
    are handled by ``_safe_host_probe`` because the Hermes terminal may be isolated.
    """
    if "tool_call" not in _tool_names(tools):
        return None
    if _HOSTNAME_RE.search(user_text) and not _LOCAL_MACHINE_RE.search(user_text):
        return {
            "bridge": "tool_call",
            "underlying": "terminal",
            "arguments": {"command": "hostname"},
            "recipe": "hostname-terminal",
        }
    return None


def _latest_tool_text(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "tool":
            return base._content_text(msg.get("content")).strip()
    return ""


def _extract_scalar(value: Any, depth: int = 0) -> str | None:
    """Best-effort extraction of a short scalar from a tool result."""
    if depth > 5:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if len(text) > 1024:
            return None
        # Some tool results are JSON serialized inside a string.
        if text[:1] in {"{", "[", '"'}:
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            if parsed is not None and parsed != value:
                nested = _extract_scalar(parsed, depth + 1)
                if nested:
                    return nested
        # Prefer the actual command output from common wrapped terminal text.
        for marker in ("Final output:\n", "final output:\n", "stdout:\n", "STDOUT:\n"):
            if marker in text:
                tail = text.rsplit(marker, 1)[-1].strip()
                if tail and len(tail) <= 512:
                    return tail
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) == 1 and len(lines[0]) <= 512:
            return lines[0]
        return None
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        if len(value) == 1:
            return _extract_scalar(value[0], depth + 1)
        return None
    if isinstance(value, dict):
        # Do not turn an explicit error object into a successful answer.
        err = value.get("error")
        if err not in (None, "", False, 0, []):
            return None
        for key in ("stdout", "output", "content", "result", "text", "value", "data", "response"):
            if key in value:
                candidate = _extract_scalar(value.get(key), depth + 1)
                if candidate:
                    return candidate
        # Last resort: one meaningful scalar field.
        candidates = []
        for key, item in value.items():
            if key in {"exit_code", "returncode", "status", "success", "duration", "elapsed"}:
                continue
            candidate = _extract_scalar(item, depth + 1)
            if candidate:
                candidates.append(candidate)
        if len(candidates) == 1:
            return candidates[0]
    return None


def _strict_fast_final(messages: Any, user_text: str) -> str | None:
    """Finalize terse tool requests without another Qwen turn."""
    if not base._STRICT_OUTPUT_RE.search(user_text):
        return None

    # If this was explicitly a local-host hostname request, the router's host
    # namespace is authoritative; ignore sandbox/container hostname results.
    host_probe = _safe_host_probe(user_text)
    if host_probe is not None:
        return host_probe[1]

    text = _latest_tool_text(messages)
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = text
    return _extract_scalar(parsed)


class Handler(base.Handler):
    server_version = "HermesFastRouter/7.0"

    def _send_text_completion(self, payload: dict[str, Any], text: str) -> None:
        created = int(time.time())
        stamp = int(time.time() * 1000)
        response_id = f"chatcmpl-hermes-fast-{stamp}"
        model = str(payload.get("model") or "local")

        if bool(payload.get("stream")):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            chunk = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}],
            }
            final = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            self._safe_write(("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode())
            self._safe_write(("data: " + json.dumps(final, ensure_ascii=False) + "\n\n").encode())
            self._safe_write(b"data: [DONE]\n\n")
            self.close_connection = True
            return

        body = {
            "id": response_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        self._json_response(200, body)

    def _send_tool_call(self, payload: dict[str, Any], plan: dict[str, Any]) -> None:
        created = int(time.time())
        stamp = int(time.time() * 1000)
        response_id = f"chatcmpl-hermes-fast-{stamp}"
        call_id = f"call_hermes_fast_{stamp}"
        model = str(payload.get("model") or "local")
        bridge_args = {
            "calls": [{"name": plan["underlying"], "arguments": plan["arguments"]}]
        }
        args_json = json.dumps(bridge_args, ensure_ascii=False, separators=(",", ":"))
        tool_call = {
            "id": call_id,
            "type": "function",
            "function": {"name": plan["bridge"], "arguments": args_json},
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
                "choices": [{
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "tool_calls": [{
                            "index": 0,
                            "id": call_id,
                            "type": "function",
                            "function": {"name": plan["bridge"], "arguments": args_json},
                        }],
                    },
                    "finish_reason": None,
                }],
            }
            final = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
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
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": None, "tool_calls": [tool_call]},
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        self._json_response(200, body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json_response(200, {"ok": True, "backend": base.BACKEND, "router_version": 7})
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
            body: dict[str, Any] = {"route": route, "reason": reason, "router_version": 7}
            probe = _safe_host_probe(text)
            if probe is not None:
                body["fast_answer"] = probe[1]
                body["fast_recipe"] = probe[0]
            self.log_message(
                "route-probe=%s reason=%s fast_recipe=%s chars=%d",
                route,
                reason,
                probe[0] if probe else "none",
                len(text),
            )
            self._json_response(200, body)
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
            fast_final = _strict_fast_final(messages, user_text)
            if fast_final:
                self.log_message(
                    "route=AGENT reason=continuation mode=deterministic-final chars=%d result_chars=%d",
                    len(user_text),
                    len(fast_final),
                )
                self._send_text_completion(payload, fast_final)
                return

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

        probe = _safe_host_probe(user_text)
        if probe is not None:
            self.log_message(
                "route=AGENT reason=%s route_ms=%d fast_dispatch=host-probe recipe=%s chars=%d",
                reason,
                elapsed_ms,
                probe[0],
                len(user_text),
            )
            self._send_text_completion(payload, probe[1])
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
        f"[fast-router] version=7 listening=http://{base.LISTEN_HOST}:{base.LISTEN_PORT} backend={base.BACKEND}",
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
