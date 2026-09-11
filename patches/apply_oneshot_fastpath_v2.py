#!/usr/bin/env python3
from __future__ import annotations

import os
import py_compile
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
TARGET = HERMES_HOME / "hermes-agent" / "hermes_cli" / "oneshot.py"
HERE = Path(__file__).resolve().parent
V1 = "HERMES_LOCAL_ONESHOT_FASTPATH_V1"
V2 = "HERMES_LOCAL_ONESHOT_FASTPATH_V2"

NEEDLE = '''        with _urlrequest.urlopen(route_req, timeout=0.8) as _resp:\n            decision = _json.loads(_resp.read().decode("utf-8"))\n        if str(decision.get("route", "")).upper() != "DIRECT":\n            return None\n'''

REPLACEMENT = '''        with _urlrequest.urlopen(route_req, timeout=0.8) as _resp:\n            decision = _json.loads(_resp.read().decode("utf-8"))\n\n        # HERMES_LOCAL_ONESHOT_FASTPATH_V2\n        # The router may resolve a tiny, read-only local fact (for example the\n        # host VPS hostname) without constructing AIAgent or invoking the LLM.\n        _fast_answer = decision.get("fast_answer")\n        if isinstance(_fast_answer, str) and _fast_answer.strip():\n            return _fast_answer.strip()\n\n        if str(decision.get("route", "")).upper() != "DIRECT":\n            return None\n'''


def main() -> int:
    if not TARGET.is_file():
        print(f"target missing: {TARGET}", file=sys.stderr)
        return 2

    text = TARGET.read_text(encoding="utf-8")
    if V2 in text:
        print(f"[oneshot-fastpath-v2] already patched: {TARGET}")
        return 0

    if V1 not in text:
        v1_script = HERE / "apply_oneshot_fastpath.py"
        if not v1_script.is_file():
            print("v1 fastpath marker missing and v1 patch script unavailable", file=sys.stderr)
            return 3
        rc = subprocess.run([sys.executable, str(v1_script)], check=False).returncode
        if rc != 0:
            return rc
        text = TARGET.read_text(encoding="utf-8")

    if text.count(NEEDLE) != 1:
        print("[oneshot-fastpath-v2] expected v1 route block changed; refusing blind patch", file=sys.stderr)
        return 4

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = HERMES_HOME / "backups" / f"oneshot-fastpath-v2-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / "oneshot.py"
    shutil.copy2(TARGET, backup)

    patched = text.replace(NEEDLE, REPLACEMENT, 1)
    TARGET.write_text(patched, encoding="utf-8")
    try:
        py_compile.compile(str(TARGET), doraise=True)
    except Exception as exc:
        shutil.copy2(backup, TARGET)
        print(f"[oneshot-fastpath-v2] compile failed; restored backup: {exc}", file=sys.stderr)
        return 5

    print("[oneshot-fastpath-v2] PATCH OK")
    print(f"[oneshot-fastpath-v2] target={TARGET}")
    print(f"[oneshot-fastpath-v2] backup={backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
