from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path.home() / '.hermes' / 'core-v2'
DB_PATH = ROOT / 'state' / 'assistant.sqlite3'
DEFAULT_TZ = (os.getenv('HERMES_TIMEZONE') or os.getenv('TZ') or 'America/Sao_Paulo').strip()

SCHEMA = '''
CREATE TABLE IF NOT EXISTS schedules (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'reminder',
  message TEXT NOT NULL,
  timezone TEXT NOT NULL,
  recurrence_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  next_run_at INTEGER,
  snoozed_until INTEGER,
  source TEXT NOT NULL DEFAULT 'natural-language',
  parent_id TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_schedules_due ON schedules(status, next_run_at);
CREATE TABLE IF NOT EXISTS schedule_occurrences (
  id TEXT PRIMARY KEY,
  schedule_id TEXT NOT NULL,
  occurrence_key TEXT NOT NULL,
  scheduled_at INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  next_retry_at INTEGER,
  delivered_at INTEGER,
  last_error TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  UNIQUE(schedule_id, occurrence_key)
);
CREATE INDEX IF NOT EXISTS idx_occ_retry ON schedule_occurrences(status, next_retry_at);
'''


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def tz(name: str | None = None) -> ZoneInfo:
    candidate = (name or DEFAULT_TZ).strip()
    try:
        return ZoneInfo(candidate)
    except Exception:
        return ZoneInfo('UTC')


def now_ts() -> int:
    return int(time.time())


def _loads(raw: str, fallback: Any) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    out = dict(row)
    out['recurrence'] = _loads(out.pop('recurrence_json', '{}'), {})
    out['metadata'] = _loads(out.pop('metadata_json', '{}'), {})
    return out


def get_schedule(ref: str) -> dict[str, Any] | None:
    key = str(ref or '').strip()
    if not key:
        return None
    with _conn() as conn:
        row = conn.execute('SELECT * FROM schedules WHERE id=?', (key,)).fetchone()
        if not row:
            row = conn.execute('SELECT * FROM schedules WHERE id LIKE ? ORDER BY created_at DESC LIMIT 1', (key + '%',)).fetchone()
        if not row:
            row = conn.execute('SELECT * FROM schedules WHERE lower(title)=lower(?) ORDER BY created_at DESC LIMIT 1', (key,)).fetchone()
    return _row(row)


def latest_schedule(kind: str | None = None) -> dict[str, Any] | None:
    with _conn() as conn:
        if kind:
            row = conn.execute('SELECT * FROM schedules WHERE kind=? ORDER BY created_at DESC LIMIT 1', (kind,)).fetchone()
        else:
            row = conn.execute('SELECT * FROM schedules ORDER BY created_at DESC LIMIT 1').fetchone()
    return _row(row)


def list_schedules(*, status: str | None = None, kinds: list[str] | None = None, limit: int = 100) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if status:
        where.append('status=?')
        params.append(status)
    if kinds:
        where.append('kind IN (' + ','.join('?' for _ in kinds) + ')')
        params.extend(kinds)
    sql = 'SELECT * FROM schedules'
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY COALESCE(next_run_at, 9223372036854775807), created_at DESC LIMIT ?'
    params.append(max(1, int(limit)))
    with _conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row(r) or {} for r in rows]


def _safe_day(year: int, month: int, day: int) -> int:
    probe = 31
    while probe >= 28:
        try:
            datetime(year, month, probe)
            return min(day, probe)
        except ValueError:
            probe -= 1
    return min(day, 28)


def _parse_hhmm(value: str | None, default: str = '09:00') -> tuple[int, int]:
    raw = value or default
    try:
        h, m = raw.split(':', 1)
        return max(0, min(23, int(h))), max(0, min(59, int(m)))
    except Exception:
        return 9, 0


def compute_next(recurrence: dict[str, Any], after_ts: int | None = None, timezone: str | None = None) -> int | None:
    zone = tz(timezone)
    after = datetime.fromtimestamp(after_ts if after_ts is not None else now_ts(), zone)
    freq = str(recurrence.get('freq') or '').lower()

    if freq == 'once':
        at = recurrence.get('at')
        if not at:
            return None
        try:
            dt = datetime.fromisoformat(str(at))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=zone)
            return int(dt.timestamp()) if dt.timestamp() > after.timestamp() else None
        except Exception:
            return None

    if freq == 'interval':
        minutes = max(1, int(recurrence.get('minutes') or 1))
        weekdays = recurrence.get('weekdays')
        weekdays = [int(x) for x in weekdays] if isinstance(weekdays, list) and weekdays else None
        ws_h, ws_m = _parse_hhmm(recurrence.get('window_start'), '00:00')
        we_h, we_m = _parse_hhmm(recurrence.get('window_end'), '23:59')
        cursor = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(0, 60 * 24 * 370):
            if weekdays is not None and cursor.weekday() not in weekdays:
                cursor = (cursor + timedelta(days=1)).replace(hour=ws_h, minute=ws_m)
                continue
            start = cursor.replace(hour=ws_h, minute=ws_m, second=0, microsecond=0)
            end = cursor.replace(hour=we_h, minute=we_m, second=0, microsecond=0)
            if cursor < start:
                cursor = start
            if cursor > end:
                cursor = (cursor + timedelta(days=1)).replace(hour=ws_h, minute=ws_m)
                continue
            elapsed = max(0, int((cursor - start).total_seconds() // 60))
            offset = (minutes - (elapsed % minutes)) % minutes
            candidate = cursor + timedelta(minutes=offset)
            if candidate <= end and (weekdays is None or candidate.weekday() in weekdays):
                return int(candidate.timestamp())
            cursor = (cursor + timedelta(days=1)).replace(hour=ws_h, minute=ws_m)
        return None

    hh, mm = _parse_hhmm(recurrence.get('time'), '09:00')
    weekdays = recurrence.get('weekdays')
    weekdays = [int(x) for x in weekdays] if isinstance(weekdays, list) and weekdays else None

    if freq == 'daily':
        cursor = after
        for add in range(0, 370):
            d = (cursor + timedelta(days=add)).date()
            candidate = datetime(d.year, d.month, d.day, hh, mm, tzinfo=zone)
            if candidate.timestamp() <= after.timestamp():
                continue
            if weekdays is not None and candidate.weekday() not in weekdays:
                continue
            return int(candidate.timestamp())
        return None

    if freq == 'weekly':
        days = weekdays or [after.weekday()]
        for add in range(0, 15):
            d = (after + timedelta(days=add)).date()
            if d.weekday() not in days:
                continue
            candidate = datetime(d.year, d.month, d.day, hh, mm, tzinfo=zone)
            if candidate.timestamp() > after.timestamp():
                return int(candidate.timestamp())
        return None

    if freq == 'monthly':
        day = max(1, min(31, int(recurrence.get('day') or 1)))
        year, month = after.year, after.month
        for _ in range(0, 25):
            actual = _safe_day(year, month, day)
            candidate = datetime(year, month, actual, hh, mm, tzinfo=zone)
            if candidate.timestamp() > after.timestamp():
                return int(candidate.timestamp())
            month += 1
            if month == 13:
                month = 1
                year += 1
        return None

    if freq == 'yearly':
        month = max(1, min(12, int(recurrence.get('month') or 1)))
        day = max(1, min(31, int(recurrence.get('day') or 1)))
        for year in range(after.year, after.year + 6):
            actual = _safe_day(year, month, day)
            candidate = datetime(year, month, actual, hh, mm, tzinfo=zone)
            if candidate.timestamp() > after.timestamp():
                return int(candidate.timestamp())
        return None
    return None


def create_schedule(title: str, message: str, recurrence: dict[str, Any], *, kind: str = 'reminder', timezone: str | None = None,
                    source: str = 'natural-language', parent_id: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    title = str(title or '').strip()[:180]
    message = str(message or '').strip()
    if not title or not message:
        raise ValueError('title_and_message_required')
    zone = (timezone or DEFAULT_TZ).strip()
    created = now_ts()
    next_run = compute_next(recurrence, created - 1, zone)
    if next_run is None and recurrence.get('freq') != 'once':
        raise ValueError('recurrence_without_next_occurrence')
    item_id = uuid.uuid4().hex[:12]
    with _conn() as conn:
        conn.execute(
            '''INSERT INTO schedules(id,title,kind,message,timezone,recurrence_json,status,next_run_at,snoozed_until,source,parent_id,metadata_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?, 'active', ?,NULL,?,?,?,?,?)''',
            (item_id, title, kind, message, zone, json.dumps(recurrence, ensure_ascii=False), next_run, source, parent_id,
             json.dumps(metadata or {}, ensure_ascii=False), created, created),
        )
    return get_schedule(item_id) or {}


def update_schedule(ref: str, **changes: Any) -> dict[str, Any]:
    item = get_schedule(ref)
    if not item:
        raise KeyError(ref)
    allowed = {'title','kind','message','status','timezone','next_run_at','snoozed_until','source','parent_id'}
    sets: list[str] = []
    values: list[Any] = []
    recurrence = changes.pop('recurrence', None)
    metadata = changes.pop('metadata', None)
    if recurrence is not None:
        sets.append('recurrence_json=?')
        values.append(json.dumps(recurrence, ensure_ascii=False))
        zone = str(changes.get('timezone') or item.get('timezone') or DEFAULT_TZ)
        sets.append('next_run_at=?')
        values.append(compute_next(recurrence, now_ts() - 1, zone))
    if metadata is not None:
        sets.append('metadata_json=?')
        values.append(json.dumps(metadata, ensure_ascii=False))
    for key, value in changes.items():
        if key in allowed:
            sets.append(f'{key}=?')
            values.append(value)
    if not sets:
        return item
    sets.append('updated_at=?')
    values.extend([now_ts(), item['id']])
    with _conn() as conn:
        conn.execute(f"UPDATE schedules SET {', '.join(sets)} WHERE id=?", values)
    return get_schedule(item['id']) or {}


def pause(ref: str) -> dict[str, Any]:
    return update_schedule(ref, status='paused')


def resume(ref: str) -> dict[str, Any]:
    item = get_schedule(ref)
    if not item:
        raise KeyError(ref)
    next_run = compute_next(item['recurrence'], now_ts() - 1, item['timezone'])
    return update_schedule(item['id'], status='active', snoozed_until=None, next_run_at=next_run)


def remove(ref: str) -> dict[str, Any]:
    return update_schedule(ref, status='cancelled')


def snooze(ref: str, until_ts: int) -> dict[str, Any]:
    return update_schedule(ref, snoozed_until=int(until_ts))


def claim_due(limit: int = 25, now: int | None = None) -> list[dict[str, Any]]:
    current = int(now or now_ts())
    claimed: list[dict[str, Any]] = []
    with _conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        rows = conn.execute(
            '''SELECT * FROM schedules WHERE status='active' AND next_run_at IS NOT NULL AND next_run_at<=?
               AND (snoozed_until IS NULL OR snoozed_until<=?) ORDER BY next_run_at LIMIT ?''',
            (current, current, max(1, int(limit))),
        ).fetchall()
        for raw in rows:
            item = _row(raw) or {}
            scheduled_at = int(item['next_run_at'])
            occurrence_key = datetime.fromtimestamp(scheduled_at, tz(item['timezone'])).isoformat()
            occ_id = uuid.uuid4().hex[:16]
            try:
                conn.execute(
                    '''INSERT INTO schedule_occurrences(id,schedule_id,occurrence_key,scheduled_at,status,attempts,created_at,updated_at)
                       VALUES(?,?,?,?, 'pending',0,?,?)''',
                    (occ_id, item['id'], occurrence_key, scheduled_at, current, current),
                )
            except sqlite3.IntegrityError:
                pass
            next_run = compute_next(item['recurrence'], scheduled_at, item['timezone'])
            next_status = 'completed' if next_run is None else 'active'
            conn.execute('UPDATE schedules SET next_run_at=?, status=?, updated_at=? WHERE id=?', (next_run, next_status, current, item['id']))
            occ = conn.execute('SELECT * FROM schedule_occurrences WHERE schedule_id=? AND occurrence_key=?', (item['id'], occurrence_key)).fetchone()
            if occ:
                payload = dict(occ)
                payload['schedule'] = item
                claimed.append(payload)
        conn.commit()
    return claimed


def failed_for_retry(limit: int = 25, now: int | None = None) -> list[dict[str, Any]]:
    current = int(now or now_ts())
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM schedule_occurrences WHERE status='retry' AND next_retry_at<=? ORDER BY next_retry_at LIMIT ?",
            (current, max(1, int(limit))),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            payload = dict(row)
            sched = conn.execute('SELECT * FROM schedules WHERE id=?', (payload['schedule_id'],)).fetchone()
            payload['schedule'] = _row(sched) or {}
            out.append(payload)
    return out


def mark_delivery(occurrence_id: str, *, ok: bool, error: str = '') -> None:
    current = now_ts()
    with _conn() as conn:
        row = conn.execute('SELECT attempts FROM schedule_occurrences WHERE id=?', (occurrence_id,)).fetchone()
        attempts = int((row['attempts'] if row else 0) or 0) + 1
        if ok:
            conn.execute(
                "UPDATE schedule_occurrences SET status='delivered',attempts=?,delivered_at=?,next_retry_at=NULL,last_error='',updated_at=? WHERE id=?",
                (attempts, current, current, occurrence_id),
            )
        else:
            if attempts >= 5:
                status, retry_at = 'failed', None
            else:
                status = 'retry'
                retry_at = current + min(60 * (2 ** (attempts - 1)), 900)
            conn.execute(
                'UPDATE schedule_occurrences SET status=?,attempts=?,next_retry_at=?,last_error=?,updated_at=? WHERE id=?',
                (status, attempts, retry_at, str(error or '')[-1000:], current, occurrence_id),
            )


def occurrence_stats(since_ts: int | None = None) -> dict[str, int]:
    since = int(since_ts or (now_ts() - 86400))
    with _conn() as conn:
        rows = conn.execute('SELECT status, COUNT(*) AS c FROM schedule_occurrences WHERE scheduled_at>=? GROUP BY status', (since,)).fetchall()
    data = {str(r['status']): int(r['c']) for r in rows}
    return {
        'total': sum(data.values()),
        'delivered': data.get('delivered', 0),
        'pending': data.get('pending', 0) + data.get('retry', 0),
        'failed': data.get('failed', 0),
    }
