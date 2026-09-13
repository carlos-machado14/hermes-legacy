#!/usr/bin/env python3
from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from event_bus import publish
from incident_store import create_incident
from memory_store import remember
from project_registry import list_projects

STATE = Path.home() / ".hermes/core-v2/state/watchers.json"
LOG = Path.home() / ".hermes/core-v2/logs/watchers.log"
INTERVAL = 60
HTTP_TIMEOUT = 8
FAILURES_BEFORE_INCIDENT = 2


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"targets": {}}


def _save(data: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def _http_ok(url: str) -> tuple[bool, str]:
    try:
        req = Request(url, headers={"User-Agent": "Hermes-Core-Watcher/2.2"})
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            code = int(getattr(resp, "status", 200))
            return 200 <= code < 500, f"HTTP {code}"
    except HTTPError as exc:
        return exc.code < 500, f"HTTP {exc.code}"
    except (URLError, socket.timeout, TimeoutError) as exc:
        return False, str(exc)
    except Exception as exc:
        return False, repr(exc)


def _service_ok(service: str) -> tuple[bool, str]:
    try:
        p = subprocess.run(["systemctl", "--user", "is-active", service], text=True, capture_output=True, timeout=5)
        out = (p.stdout or p.stderr or "").strip()
        return p.returncode == 0 and out == "active", out or f"exit={p.returncode}"
    except Exception as exc:
        return False, repr(exc)


def once() -> dict:
    state = _load()
    target_state = state.setdefault("targets", {})
    report: dict[str, dict] = {}

    for project in list_projects():
        if project.get("enabled", True) is False:
            continue
        name = str(project.get("name") or "unnamed")
        checks: list[tuple[str, bool, str]] = []

        health_url = str(project.get("health_url") or "").strip()
        if health_url:
            ok, detail = _http_ok(health_url)
            checks.append((f"http:{health_url}", ok, detail))

        for service in project.get("services") or []:
            service_name = str(service).strip()
            if service_name:
                ok, detail = _service_ok(service_name)
                checks.append((f"service:{service_name}", ok, detail))

        project_result = {"ok": True, "checks": []}
        for key, ok, detail in checks:
            state_key = f"{name}:{key}"
            current = target_state.setdefault(state_key, {"failures": 0, "incident_open": False})
            if ok:
                if current.get("incident_open"):
                    publish("watcher.recovered", {"project": name, "target": key, "detail": detail}, source="watcher")
                    remember("incident", f"{name} recuperado", {"target": key, "detail": detail}, True)
                current["failures"] = 0
                current["incident_open"] = False
            else:
                current["failures"] = int(current.get("failures", 0)) + 1
                project_result["ok"] = False
                if current["failures"] >= FAILURES_BEFORE_INCIDENT and not current.get("incident_open"):
                    incident = create_incident(
                        "watcher.failure",
                        f"Falha detectada em {name}",
                        {"project": name, "target": key, "detail": detail, "failures": current["failures"]},
                        "critical" if key.startswith("service:") else "warning",
                    )
                    current["incident_open"] = True
                    publish("watcher.failure", incident, source="watcher")
                    remember("incident", incident["summary"], incident, False)
            current["last_ok"] = bool(ok)
            current["last_detail"] = detail
            current["last_check"] = int(time.time())
            project_result["checks"].append({"target": key, "ok": ok, "detail": detail})

        report[name] = project_result

    state["last_check"] = int(time.time())
    state["last_report"] = report
    _save(state)
    return report


def main() -> int:
    _log("watcher-engine started")
    remember("watcher", "watcher engine started", {"interval": INTERVAL}, True)
    while True:
        try:
            once()
        except Exception as exc:
            _log(f"error={exc!r}")
            remember("watcher", "watcher engine error", {"error": repr(exc)}, False)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
