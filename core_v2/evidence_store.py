from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

DB = Path.home() / '.hermes/core-v2/state/evidence.sqlite3'


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute('''CREATE TABLE IF NOT EXISTS evidence(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at INTEGER NOT NULL,
        query TEXT NOT NULL,
        url TEXT NOT NULL,
        title TEXT,
        snippet TEXT,
        kind TEXT NOT NULL,
        payload TEXT
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_evidence_query ON evidence(query)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_evidence_url ON evidence(url)')
    return conn


def add(query: str, url: str, title: str = '', snippet: str = '', kind: str = 'search', payload: dict[str, Any] | None = None) -> int:
    with _conn() as c:
        cur = c.execute('INSERT INTO evidence(created_at,query,url,title,snippet,kind,payload) VALUES(?,?,?,?,?,?,?)', (
            int(time.time()), str(query), str(url), str(title), str(snippet), str(kind), json.dumps(payload or {}, ensure_ascii=False)
        ))
        return int(cur.lastrowid)


def recent(limit: int = 100) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute('SELECT * FROM evidence ORDER BY id DESC LIMIT ?', (max(1, min(int(limit), 500)),)).fetchall()
    out=[]
    for row in rows:
        item=dict(row)
        try: item['payload']=json.loads(item.get('payload') or '{}')
        except Exception: item['payload']={}
        out.append(item)
    return out
