#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / ".hermes/core-v2/state"
PROJECTS_FILE = STATE_DIR / "projects.json"


def _load() -> dict[str, Any]:
    try:
        return json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"projects": []}


def _save(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_projects() -> list[dict[str, Any]]:
    return list(_load().get("projects") or [])


def get_project(name: str) -> dict[str, Any] | None:
    key = name.strip().casefold()
    for item in list_projects():
        if str(item.get("name", "")).strip().casefold() == key:
            return item
    return None


def upsert_project(project: dict[str, Any]) -> dict[str, Any]:
    name = str(project.get("name") or "").strip()
    if not name:
        raise ValueError("project.name é obrigatório")
    data = _load()
    projects = list(data.get("projects") or [])
    current = None
    for idx, item in enumerate(projects):
        if str(item.get("name", "")).strip().casefold() == name.casefold():
            merged = dict(item)
            merged.update(project)
            merged["name"] = name
            projects[idx] = merged
            current = merged
            break
    if current is None:
        current = dict(project)
        current["name"] = name
        projects.append(current)
    data["projects"] = projects
    _save(data)
    return current


def remove_project(name: str) -> bool:
    data = _load()
    key = name.strip().casefold()
    projects = list(data.get("projects") or [])
    kept = [p for p in projects if str(p.get("name", "")).strip().casefold() != key]
    changed = len(kept) != len(projects)
    if changed:
        data["projects"] = kept
        _save(data)
    return changed


def public_summary() -> list[dict[str, Any]]:
    out = []
    for project in list_projects():
        out.append({
            "name": project.get("name"),
            "repo": project.get("repo"),
            "health_url": project.get("health_url"),
            "services": project.get("services", []),
            "enabled": project.get("enabled", True),
        })
    return out
