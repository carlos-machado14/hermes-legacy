#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from event_bus import recent as recent_events
from incident_store import recent_incidents
from memory_store import recent as recent_memory
from project_registry import list_projects, upsert_project, remove_project
from project_ops import project_status, restart_project

ROOT = Path.home() / ".hermes/core-v2"
HOST = os.getenv("HERMES_CORE_API_HOST", "127.0.0.1")
PORT = int(os.getenv("HERMES_CORE_API_PORT", "8090"))
TOKEN = os.getenv("HERMES_CORE_API_TOKEN", "").strip()


def _json(handler: BaseHTTPRequestHandler, status: int, payload: dict | list) -> None:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _auth_ok(handler: BaseHTTPRequestHandler) -> bool:
    if not TOKEN:
        return True
    value = handler.headers.get("Authorization", "")
    return value == f"Bearer {TOKEN}"


def _read_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(min(length, 1024 * 1024))
    return json.loads(raw.decode("utf-8"))


def _run_core(message: str) -> tuple[int, str]:
    py = ROOT / "venv/bin/python"
    core = ROOT / "hermes_core.py"
    p = subprocess.run([str(py), str(core), message], text=True, capture_output=True, timeout=30, cwd=str(ROOT))
    text = (p.stdout or p.stderr or "").strip()
    return p.returncode, text


class Handler(BaseHTTPRequestHandler):
    server_version = "HermesCoreAPI/2.3"

    def log_message(self, fmt: str, *args) -> None:
        return

    def _guard(self) -> bool:
        if not _auth_ok(self):
            _json(self, 401, {"ok": False, "error": "unauthorized"})
            return False
        return True

    def do_GET(self) -> None:
        if not self._guard():
            return
        path = urlparse(self.path).path
        if path == "/health":
            _json(self, 200, {"ok": True, "version": "2.3", "api": "active"})
        elif path == "/events":
            _json(self, 200, {"ok": True, "events": recent_events(100)})
        elif path == "/memory":
            _json(self, 200, {"ok": True, "memory": recent_memory(100)})
        elif path == "/incidents":
            _json(self, 200, {"ok": True, "incidents": recent_incidents(100)})
        elif path == "/projects":
            _json(self, 200, {"ok": True, "projects": list_projects()})
        else:
            _json(self, 404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        if not self._guard():
            return
        path = urlparse(self.path).path
        try:
            body = _read_body(self)
        except Exception as exc:
            _json(self, 400, {"ok": False, "error": f"invalid_json: {exc}"})
            return

        if path == "/message":
            message = str(body.get("message") or "").strip()
            if not message:
                _json(self, 400, {"ok": False, "error": "message_required"})
                return
            try:
                code, reply = _run_core(message)
                _json(self, 200 if code == 0 else 500, {"ok": code == 0, "reply": reply})
            except subprocess.TimeoutExpired:
                _json(self, 504, {"ok": False, "error": "core_timeout"})
        elif path == "/projects":
            try:
                project = upsert_project(dict(body))
                _json(self, 200, {"ok": True, "project": project})
            except Exception as exc:
                _json(self, 400, {"ok": False, "error": str(exc)})
        elif path == "/projects/remove":
            name = str(body.get("name") or "").strip()
            _json(self, 200, {"ok": True, "removed": remove_project(name) if name else False})
        elif path == "/projects/status":
            name = str(body.get("name") or "").strip()
            report = project_status(name) if name else {"ok": False, "error": "name_required"}
            _json(self, 200 if report.get("ok") else 404 if report.get("error") == "project_not_found" else 400, report)
        elif path == "/projects/restart":
            name = str(body.get("name") or "").strip()
            report = restart_project(name) if name else {"ok": False, "error": "name_required"}
            _json(self, 200 if report.get("ok") else 409, report)
        else:
            _json(self, 404, {"ok": False, "error": "not_found"})


def main() -> int:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Hermes Core API 2.3 listening on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
