#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any

HOME = Path.home()
VAULT = HOME / '.hermes' / 'memory'
STATE_DIR = HOME / '.hermes' / 'core-v2' / 'state'
DB = STATE_DIR / 'memory_index.sqlite3'
SECTIONS = ('profile', 'goals', 'projects', 'business', 'conversations', 'decisions', 'daily')


def _ensure() -> None:
    VAULT.mkdir(parents=True, exist_ok=True); STATE_DIR.mkdir(parents=True, exist_ok=True)
    for name in SECTIONS: (VAULT / name).mkdir(parents=True, exist_ok=True)


def _slug(text: str) -> str:
    value = re.sub(r'[^a-zA-Z0-9\-_.]+', '-', text.strip().lower()).strip('-')
    return value[:80] or 'nota'


def _db() -> sqlite3.Connection:
    _ensure(); conn = sqlite3.connect(DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS documents (
        path TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,
        mtime REAL NOT NULL, indexed_at INTEGER NOT NULL)''')
    conn.commit(); return conn


def write_note(section: str, title: str, body: str, *, filename: str | None = None) -> Path:
    _ensure(); section = section if section in SECTIONS else 'conversations'
    path = VAULT / section / (filename or f'{_slug(title)}.md')
    content = f'# {title}\n\n{body.strip()}\n'
    try:
        if path.exists() and path.read_text(encoding='utf-8') == content:
            return path
    except Exception: pass
    path.write_text(content, encoding='utf-8'); index_file(path); return path


def append_daily(role: str, text: str) -> Path:
    _ensure(); now = datetime.now(); path = VAULT / 'daily' / f'{now:%Y-%m-%d}.md'
    if not path.exists(): path.write_text(f'# Diário {now:%Y-%m-%d}\n\n', encoding='utf-8')
    who = 'Usuário' if role == 'user' else 'Hermes'
    with path.open('a', encoding='utf-8') as f: f.write(f'## {now:%H:%M:%S} — {who}\n\n{text.strip()}\n\n')
    index_file(path); return path


def index_file(path: Path) -> None:
    try: text = path.read_text(encoding='utf-8')
    except Exception: return
    title = path.stem.replace('-', ' ')
    first = next((line[2:].strip() for line in text.splitlines() if line.startswith('# ')), '')
    if first: title = first
    st = path.stat(); rel = str(path.relative_to(VAULT))
    with _db() as conn:
        conn.execute('INSERT INTO documents(path,title,content,mtime,indexed_at) VALUES(?,?,?,?,?) '
                     'ON CONFLICT(path) DO UPDATE SET title=excluded.title, content=excluded.content, mtime=excluded.mtime, indexed_at=excluded.indexed_at',
                     (rel, title, text, st.st_mtime, int(time.time())))


def refresh_index() -> int:
    _ensure(); known: dict[str, float] = {}
    with _db() as conn:
        for path, mtime in conn.execute('SELECT path,mtime FROM documents'): known[str(path)] = float(mtime)
    count = 0; present: set[str] = set()
    for path in VAULT.rglob('*.md'):
        rel = str(path.relative_to(VAULT)); present.add(rel)
        try: mtime = path.stat().st_mtime
        except Exception: continue
        if abs(known.get(rel, -1) - mtime) > 0.001: index_file(path); count += 1
    stale = set(known) - present
    if stale:
        with _db() as conn: conn.executemany('DELETE FROM documents WHERE path=?', [(p,) for p in stale])
    return count


def _terms(query: str) -> list[str]:
    stop = {'para','com','que','uma','uns','umas','dos','das','de','do','da','em','no','na','nos','nas','e','o','a','os','as','meu','minha','meus','minhas','isso','essa','esse'}
    return [w for w in re.findall(r'[\wÀ-ÿ]{3,}', query.lower()) if w not in stop][:12]


def retrieve(query: str, *, limit: int = 5, max_chars: int = 3600) -> str:
    refresh_index(); terms = _terms(query)
    if not terms: return ''
    clauses = ' OR '.join(['lower(title) LIKE ? OR lower(content) LIKE ?' for _ in terms])
    params: list[str] = []
    for term in terms: params.extend([f'%{term}%', f'%{term}%'])
    with _db() as conn:
        rows = conn.execute(f'SELECT path,title,content,indexed_at FROM documents WHERE {clauses} ORDER BY indexed_at DESC LIMIT 80', params).fetchall()
    scored: list[tuple[float, str, str, str]] = []; now = time.time()
    for path, title, content, indexed_at in rows:
        hay = f'{title}\n{content}'.lower(); score = 0.0
        for term in terms:
            n = hay.count(term)
            if n: score += min(n, 8) * 2.0 + (3.0 if term in str(title).lower() else 0.0)
        if score <= 0: continue
        age_days = max(0.0, (now - float(indexed_at or now)) / 86400)
        score += max(0.0, 2.0 - age_days / 30.0)
        scored.append((score, str(path), str(title), str(content)))
    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[str] = []; used = 0
    for _, path, title, content in scored[:max(1, limit)]:
        snippet = content.strip()
        if len(snippet) > 900: snippet = snippet[:900].rsplit(' ', 1)[0] + '…'
        block = f'[[{title}]] ({path})\n{snippet}'
        if used + len(block) > max_chars: break
        out.append(block); used += len(block)
    return '\n\n'.join(out)


def sync_state_snapshots() -> None:
    _ensure(); mappings = [
        (STATE_DIR / 'personal_profile.json', 'profile', 'Perfil'),
        (STATE_DIR / 'goals.json', 'goals', 'Objetivos'),
        (STATE_DIR / 'tasks.json', 'goals', 'Tarefas'),
        (STATE_DIR / 'leads.json', 'business', 'Leads'),
        (STATE_DIR / 'decisions.json', 'decisions', 'Decisões'),
        (STATE_DIR / 'learning.json', 'business', 'Aprendizados'),
    ]
    for source, section, title in mappings:
        if not source.exists(): continue
        try:
            data: Any = json.loads(source.read_text(encoding='utf-8'))
            write_note(section, title, '```json\n' + json.dumps(data, ensure_ascii=False, indent=2) + '\n```', filename=f'{_slug(title)}.md')
        except Exception: continue


def stats() -> dict[str, Any]:
    refresh_index()
    with _db() as conn: count = int(conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0])
    size = DB.stat().st_size if DB.exists() else 0
    return {'vault': str(VAULT), 'documents': count, 'index_bytes': size}


def summary() -> str:
    s = stats()
    return f"Memory Vault ativo | notas={s['documents']} | índice={s['index_bytes']/1024:.1f} KB | vault={s['vault']}"
