from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path.home() / '.hermes' / 'core-v2'
DB_PATH = ROOT / 'state' / 'jobs.sqlite3'

SCHEMA = '''
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  request TEXT NOT NULL,
  status TEXT NOT NULL,
  plan_json TEXT NOT NULL DEFAULT '[]',
  current_step INTEGER NOT NULL DEFAULT 0,
  result TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS checkpoints (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  step_index INTEGER NOT NULL,
  step_title TEXT NOT NULL,
  status TEXT NOT NULL,
  output TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_checkpoints_job ON checkpoints(job_id, step_index);
'''


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def create_job(request: str, title: str | None = None) -> dict[str, Any]:
    request = request.strip()
    if not request:
        raise ValueError('request_required')
    now = int(time.time())
    job_id = uuid.uuid4().hex[:12]
    title = (title or request[:90]).strip()
    with _conn() as conn:
        conn.execute(
            'INSERT INTO jobs(id,title,request,status,created_at,updated_at) VALUES(?,?,?,?,?,?)',
            (job_id, title, request, 'queued', now, now),
        )
    return get_job(job_id) or {}


def get_job(job_id: str) -> dict[str, Any] | None:
    with _conn() as conn:
        row = conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
    if not row:
        return None
    out = dict(row)
    try:
        out['plan'] = json.loads(out.pop('plan_json') or '[]')
    except Exception:
        out['plan'] = []
    return out


def list_jobs(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with _conn() as conn:
        if status:
            rows = conn.execute('SELECT * FROM jobs WHERE status=? ORDER BY updated_at DESC LIMIT ?', (status, limit)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?', (limit,)).fetchall()
    return [get_job(str(r['id'])) or {} for r in rows]


def update_job(job_id: str, **fields: Any) -> dict[str, Any]:
    allowed = {'title','status','current_step','result','error','attempts'}
    values: list[Any] = []
    sets: list[str] = []
    if 'plan' in fields:
        sets.append('plan_json=?')
        values.append(json.dumps(fields['plan'], ensure_ascii=False))
    for key, value in fields.items():
        if key in allowed:
            sets.append(f'{key}=?')
            values.append(value)
    if not sets:
        return get_job(job_id) or {}
    sets.append('updated_at=?')
    values.append(int(time.time()))
    values.append(job_id)
    with _conn() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", values)
    return get_job(job_id) or {}


def checkpoint(job_id: str, step_index: int, step_title: str, status: str, output: str = '') -> None:
    with _conn() as conn:
        conn.execute(
            'INSERT INTO checkpoints(job_id,step_index,step_title,status,output,created_at) VALUES(?,?,?,?,?,?)',
            (job_id, step_index, step_title, status, output[-12000:], int(time.time())),
        )


def checkpoints(job_id: str) -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute('SELECT * FROM checkpoints WHERE job_id=? ORDER BY id', (job_id,)).fetchall()
    return [dict(r) for r in rows]


def recover_interrupted() -> int:
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status='queued', updated_at=? WHERE status IN ('planning','running','validating')",
            (int(time.time()),),
        )
        return int(cur.rowcount or 0)
