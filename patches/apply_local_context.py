#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser().resolve()
target = home / "hermes-agent" / "agent" / "model_metadata.py"

if not target.is_file():
    raise SystemExit(f"Hermes source not found: {target}")

text = target.read_text(encoding="utf-8")
marker = "HERMES_MIN_CONTEXT_LENGTH"

if marker in text:
    print(f"already patched: {target}")
    raise SystemExit(0)

pattern = re.compile(r"^MINIMUM_CONTEXT_LENGTH\s*=\s*64_?000\s*$", re.MULTILINE)
if not pattern.search(text):
    raise SystemExit(
        "Could not find the upstream 64k minimum-context constant. "
        "Hermes may have changed; refusing to patch blindly."
    )

replacement = '''def _resolve_minimum_context_length() -> int:\n    """Local-only distribution override.\n\n    Upstream Hermes defaults to a 64k hard floor. Small local models often have\n    16k/32k native windows, so our distribution makes the floor configurable.\n    The lower safety bound avoids obviously unusable contexts.\n    """\n    raw = os.environ.get("HERMES_MIN_CONTEXT_LENGTH", "16384").strip()\n    try:\n        value = int(raw)\n    except (TypeError, ValueError):\n        value = 16_384\n    return max(8_192, value)\n\n\nMINIMUM_CONTEXT_LENGTH = _resolve_minimum_context_length()'''

backup_root = home / "backups" / f"local-context-patch-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
backup_root.mkdir(parents=True, exist_ok=True)
backup = backup_root / "model_metadata.py"
shutil.copy2(target, backup)

target.write_text(pattern.sub(replacement, text, count=1), encoding="utf-8")

# Fail immediately if the resulting file has a syntax error.
compile(target.read_text(encoding="utf-8"), str(target), "exec")

print(f"patched: {target}")
print(f"backup : {backup}")
print("minimum context default: 16384 (override with HERMES_MIN_CONTEXT_LENGTH)")
