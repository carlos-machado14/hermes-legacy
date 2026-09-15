from __future__ import annotations

import json
import os
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
  source_platform TEXT NOT NULL DEFAULT '',
  source_chat_id TEXT NOT NULL DEFAULT '',
  source_user_id TEXT NOT NULL DEFAULT '',
  notified_at INTEGER,
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
CREATE INDEX IF NOT EXISTS idx_jobs_notify ON jobs(status, notified_at);
CREATE INDEX IF NOT EXISTS idx_checkpoints_job ON checkpoints(job_id, step_index);
'''

_EXTRA_COLUMNS = {
    'source_platform': "TEXT NOT NULL DEFAULT ''",
    'source_chat_id': "TEXT NOT NULL DEFAULT ''",
    'source_user_id': "TEXT NOT NULL DEFAULT ''",
    'notified_at': 'INTEGER',
}


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    cols = {str(r['name']) for r in conn.execute('PRAGMA table_info(jobs)').fetchall()}
    for name, ddl in _EXTRA_COLUMNS.items():
        if name not in cols:
            conn.execute(f'ALTER TABLE jobs ADD COLUMN {name} {ddl}')
    conn.commit()
    return conn


def create_job(request: str, title: str | None = None, *, source_platform: str | None = None,
               source_chat_id: str | None = None, source_user_id: str | None = None) -> dict[str, Any]:
    request = request.strip()
    if not request:
        raise ValueError('request_required')
    now = int(time.time())
    job_id = uuid.uuid4().hex[:12]
    title = (title or request[:90]).strip()
    platform = str(source_platform if source_platform is not None else os.getenv('HERMES_SOURCE_PLATFORM', '')).strip()
    chat_id = str(source_chat_id if source_chat_id is not None else os.getenv('HERMES_SOURCE_CHAT_ID', '')).strip()
    user_id = str(source_user_id if source_user_id is not None else os.getenv('HERMES_SOURCE_USER_ID', '')).strip()
    with _conn() as conn:
        conn.execute(
            '''INSERT INTO jobs(id,title,request,status,source_platform,source_chat_id,source_user_id,created_at,updated_at)
               VALUES(?,?,?, 'queued', ?,?,?,?,?)''',
            (job_id, title, request, platform, chat_id, user_id, now, now),
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
            rows = conn.execute('SELECT id FROM jobs WHERE status=? ORDER BY updated_at DESC LIMIT ?', (status, limit)).fetchall()
        else:
            rows = conn.execute('SELECT id FROM jobs ORDER BY updated_at DESC LIMIT ?', (limit,)).fetchall()
    return [get_job(str(r['id'])) or {} for r in rows]


def list_unnotified(limit: int = 50) -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id FROM jobs WHERE status IN ('done','needs_attention') AND notified_at IS NULL AND source_chat_id<>'' ORDER BY updated_at LIMIT ?",
            (limit,),
        ).fetchall()
    return [get_job(str(r['id'])) or {} for r in rows]


def claim_jobs(limit: int = 4) -> list[dict[str, Any]]:
    now = int(time.time())
    ids: list[str] = []
    with _conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        rows = conn.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT ?", (max(1, int(limit)),)).fetchall()
        ids = [str(r['id']) for r in rows]
        for job_id in ids:
            conn.execute("UPDATE jobs SET status='claimed', updated_at=? WHERE id=? AND status='queued'", (now, job_id))
        conn.commit()
    return [get_job(job_id) or {} for job_id in ids]


def update_job(job_id: str, **fields: Any) -> dict[str, Any]:
    allowed = {
        'title','status','current_step','result','error','attempts',
        'source_platform','source_chat_id','source_user_id','notified_at',
    }
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


def mark_notified(job_id: str) -> dict[str, Any]:
    return update_job(job_id, notified_at=int(time.time()))


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
            "UPDATE jobs SET status='queued', updated_at=? WHERE status IN ('claimed','planning','running','validating')",
            (int(time.time()),),
        )
        return int(cur.rowcount or 0)
