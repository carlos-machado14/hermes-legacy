#!/usr/bin/env python3
from __future__ import annotations

import os
import py_compile
import shutil
import sys
import time
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
TARGET = HERMES_HOME / "hermes-agent" / "hermes_cli" / "oneshot.py"
MARKER = "HERMES_LOCAL_ONESHOT_FASTPATH_V1"

HELPER = r'''
# HERMES_LOCAL_ONESHOT_FASTPATH_V1

def _hermes_local_fastpath(prompt: str, *, model=None, provider=None, toolsets=None, skills=None):
    """Best-effort local DIRECT path before AIAgent construction.

    Only active for the default local invocation (no explicit model/provider/toolsets/skills).
    The deterministic router decides DIRECT vs AGENT without invoking an LLM. AGENT falls
    through to the normal Hermes oneshot path unchanged. Any fast-path error also falls back.
    """
    if model or provider or toolsets or skills:
        return None
    if not isinstance(prompt, str) or not prompt.strip():
        return None

    try:
        import json as _json
        import re as _re
        import urllib.request as _urlrequest

        router = os.getenv("HERMES_FAST_ROUTER_URL", "http://127.0.0.1:8089").rstrip("/")
        route_req = _urlrequest.Request(
            router + "/v1/route",
            data=_json.dumps({"text": prompt}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _urlrequest.urlopen(route_req, timeout=0.8) as _resp:
            decision = _json.loads(_resp.read().decode("utf-8"))
        if str(decision.get("route", "")).upper() != "DIRECT":
            return None

        model_id_path = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))) / "local-runtime" / "model.id"
        model_id = model_id_path.read_text(encoding="utf-8").strip() if model_id_path.exists() else ""
        if not model_id:
            return None

        strict = _re.search(
            r"\b(somente|apenas|s[oó]|only|just|one word|uma palavra|sem explica[cç][aã]o|sem texto extra|no explanation|nothing else)\b",
            prompt,
            _re.IGNORECASE,
        ) is not None
        max_tokens = 12 if strict else 160
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": "You are Hermes. Answer accurately and concisely in the user's language. Follow the requested output format exactly."},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": 0 if strict else 0.2,
        }
        infer_req = _urlrequest.Request(
            router + "/v1/chat/completions",
            data=_json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _urlrequest.urlopen(infer_req, timeout=float(os.getenv("HERMES_FASTPATH_TIMEOUT", "300"))) as _resp:
            result = _json.loads(_resp.read().decode("utf-8"))
        text = (((result.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        return text or None
    except Exception:
        return None

'''

CALL_NEEDLE = "    logging.disable(logging.CRITICAL)\n"
CALL_BLOCK = '''    logging.disable(logging.CRITICAL)\n\n    # Local pre-agent fast path: a deterministic route probe runs before Hermes builds\n    # AIAgent, resolves toolsets/MCP, opens session state, and assembles the full prompt.\n    # AGENT requests fall through unchanged.\n    if usage_file is None:\n        _fast_response = _hermes_local_fastpath(\n            prompt, model=model, provider=provider, toolsets=toolsets, skills=skills\n        )\n        if _fast_response is not None:\n            sys.stdout.write(_fast_response)\n            if not _fast_response.endswith("\\n"):\n                sys.stdout.write("\\n")\n            sys.stdout.flush()\n            return 0\n'''


def main() -> int:
    if not TARGET.is_file():
        print(f"target missing: {TARGET}", file=sys.stderr)
        return 2

    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print(f"[oneshot-fastpath] already patched: {TARGET}")
        return 0

    def_pos = text.find("\ndef run_oneshot(")
    if def_pos < 0:
        print("[oneshot-fastpath] expected run_oneshot marker not found; refusing blind patch", file=sys.stderr)
        return 3
    if text.count(CALL_NEEDLE) != 1:
        print("[oneshot-fastpath] logging.disable marker changed; refusing blind patch", file=sys.stderr)
        return 4

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = HERMES_HOME / "backups" / f"oneshot-fastpath-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / "oneshot.py"
    shutil.copy2(TARGET, backup)

    patched = text[: def_pos + 1] + HELPER + text[def_pos + 1 :]
    patched = patched.replace(CALL_NEEDLE, CALL_BLOCK, 1)
    TARGET.write_text(patched, encoding="utf-8")

    try:
        py_compile.compile(str(TARGET), doraise=True)
    except Exception as exc:
        shutil.copy2(backup, TARGET)
        print(f"[oneshot-fastpath] compile failed; restored backup: {exc}", file=sys.stderr)
        return 5

    print("[oneshot-fastpath] PATCH OK")
    print(f"[oneshot-fastpath] target={TARGET}")
    print(f"[oneshot-fastpath] backup={backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
