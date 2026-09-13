#!/usr/bin/env python3
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / ".hermes/core-v2/state"
INCIDENTS = STATE_DIR / "incidents.jsonl"


def create_incident(kind: str, summary: str, details: dict[str, Any] | None = None, severity: str = "warning") -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    item = {
        "id": uuid.uuid4().hex[:12],
        "ts": int(time.time()),
        "kind": kind,
        "severity": severity,
        "summary": summary,
        "details": details or {},
        "status": "open",
    }
    with INCIDENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return item


def recent_incidents(limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    try:
        rows = []
        for line in INCIDENTS.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                if status is None or item.get("status") == status:
                    rows.append(item)
            except Exception:
                pass
        return rows[-max(1, min(limit, 200)):]
    except Exception:
        return []
