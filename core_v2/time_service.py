#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import json
import re
import signal
import sqlite3
import time
import shutil
import subprocess
from pathlib import Path
from typing import Any, IO

from delivery import send_telegram
from temporal_parser import parse
from time_store import DB_PATH, claim_due, create_schedule, list_schedules, mark_delivery, occurrence_stats

ROOT = Path.home() / '.hermes' / 'core-v2'
STATE = ROOT / 'state'
LEGACY = STATE / 'managed_crons.json'
LOG = ROOT / 'logs' / 'time-engine.log'
LOCK = STATE / 'time-engine.lock'
RUNNING = True
_LOCK_HANDLE: IO[str] | None = None


def _log(message: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a', encoding='utf-8') as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def _acquire_singleton() -> bool:
    """Guarantee only one Time Engine process can deliver reminders."""
    global _LOCK_HANDLE
    STATE.mkdir(parents=True, exist_ok=True)
    handle = LOCK.open('a+', encoding='utf-8')
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return False
    handle.seek(0)
    handle.truncate()
    handle.write(str(Path('/proc/self').resolve()))
    handle.flush()
    _LOCK_HANDLE = handle
    return True


def _stop(*_args: Any) -> None:
    global RUNNING
    RUNNING = False


def _format_occurrence(item: dict[str, Any]) -> str:
    kind = str(item.get('kind') or 'reminder')
    message = str(item.get('message') or item.get('title') or 'Lembrete')
    if kind == 'event':
        return f'📅 Evento\n{message}'
    if kind == 'routine':
        return f'🔔 Rotina\n{message}'
    if kind == 'commitment':
        return f'✅ Compromisso pendente\n{message}'
    if kind == 'alert':
        return f'⏰ Alerta\n{message}'
    return f'🔔 Lembrete\n{message}'


def _finalize_failed_delivery(occurrence_id: str, error: str) -> None:
    """Finish a failed Telegram attempt without scheduling another send.

    Telegram sendMessage has no idempotency key. If the connection fails after
    Telegram accepted the request, retrying can create duplicate notifications.
    Reminder delivery therefore uses at-most-once semantics: one network send per
    occurrence. Failures become terminal and are surfaced by the health monitor.
    """
    current = int(time.time())
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        row = conn.execute(
            'SELECT attempts FROM schedule_occurrences WHERE id=?',
            (occurrence_id,),
        ).fetchone()
        attempts = int((row[0] if row else 0) or 0) + 1
        conn.execute(
            """UPDATE schedule_occurrences
               SET status='failed', attempts=?, next_retry_at=NULL,
                   last_error=?, updated_at=?
               WHERE id=?""",
            (attempts, f'at_most_once:{str(error or "telegram_delivery_failed")[-900:]}', current, occurrence_id),
        )


def _quarantine_legacy_retries() -> int:
    """Disable retry rows created by earlier versions before the service starts."""
    current = int(time.time())
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        cur = conn.execute(
            """UPDATE schedule_occurrences
               SET status='failed', next_retry_at=NULL,
                   last_error='at_most_once:legacy_retry_disabled:' || last_error,
                   updated_at=?
               WHERE status='retry'""",
            (current,),
        )
        return int(cur.rowcount or 0)


def _deliver(occ: dict[str, Any]) -> None:
    item = occ.get('schedule') or {}
    occurrence_id = str(occ['id'])
    if not item:
        _finalize_failed_delivery(occurrence_id, 'schedule_missing')
        return

    # Exactly one Telegram request is made for each occurrence. We intentionally
    # do not retry failed/ambiguous responses because sendMessage is not
    # idempotent and a retry can produce duplicate notifications.
    ok, error = send_telegram(_format_occurrence(item), attempts=1)
    if ok:
        mark_delivery(occurrence_id, ok=True)
        state = 'delivered'
    else:
        _finalize_failed_delivery(occurrence_id, error)
        state = 'failed_no_retry'
    _log(
        f"occurrence={occ.get('id')} schedule={item.get('id')} state={state} "
        f"ok={ok} error={error[:160] if error else ''}"
    )


def _already_migrated(legacy_id: str) -> bool:
    for item in list_schedules(limit=2000):
        meta = item.get('metadata') or {}
        if str(meta.get('legacy_cron_id') or '') == legacy_id:
            return True
    return False


def _legacy_fingerprint(message: str, recurrence: dict[str, Any], timezone: str | None) -> tuple[str, str, str]:
    normalized_message = re.sub(r'\s+', ' ', str(message or '').strip()).casefold()
    normalized_tz = str(timezone or 'America/Sao_Paulo').strip()
    normalized_recurrence = json.dumps(recurrence or {}, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return normalized_message, normalized_tz, normalized_recurrence


def _existing_legacy_fingerprints() -> set[tuple[str, str, str]]:
    out: set[tuple[str, str, str]] = set()
    for item in list_schedules(limit=5000):
        if str(item.get('source') or '') != 'legacy-cron-migration':
            continue
        out.add(_legacy_fingerprint(
            str(item.get('message') or ''),
            item.get('recurrence') or {},
            str(item.get('timezone') or ''),
        ))
    return out


def _dedupe_legacy_schedules() -> int:
    """Cancel duplicated schedules created by old migration runs.

    Only schedules whose source is legacy-cron-migration are touched. Natural
    schedules created by the user are never collapsed automatically.
    """
    current = int(time.time())
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT id,message,timezone,recurrence_json,status,created_at
               FROM schedules
               WHERE source='legacy-cron-migration'
               ORDER BY created_at,id"""
        ).fetchall()

        groups: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
        for row in rows:
            try:
                recurrence = json.loads(str(row['recurrence_json'] or '{}'))
            except Exception:
                recurrence = {}
            key = _legacy_fingerprint(str(row['message'] or ''), recurrence, str(row['timezone'] or ''))
            groups.setdefault(key, []).append(row)

        cancelled = 0
        for duplicates in groups.values():
            if len(duplicates) <= 1:
                continue
            active = [row for row in duplicates if str(row['status'] or '') == 'active']
            keeper = active[0] if active else duplicates[0]
            for row in duplicates:
                if str(row['id']) == str(keeper['id']):
                    continue
                if str(row['status'] or '') == 'cancelled' and row['id'] != keeper['id']:
                    continue
                conn.execute(
                    """UPDATE schedules
                       SET status='cancelled', next_run_at=NULL, snoozed_until=NULL, updated_at=?
                       WHERE id=?""",
                    (current, str(row['id'])),
                )
                cancelled += 1
        conn.commit()
    return cancelled


def _legacy_parse(schedule: str, message: str) -> dict[str, Any] | None:
    s = str(schedule or '').strip().casefold()
    synthetic = message
    m = re.fullmatch(r'every\s+(\d+)m', s)
    if m:
        synthetic = f'a cada {m.group(1)} minutos {message}'
    else:
        m = re.fullmatch(r'every\s+(\d+)h', s)
        if m:
            synthetic = f'a cada {m.group(1)} horas {message}'
        m = re.fullmatch(r'every\s+day\s+at\s+(\d{2}:\d{2})', s)
        if m:
            synthetic = f'todo dia às {m.group(1)}h {message}'
        m = re.fullmatch(r'weekdays\s+at\s+(\d{2}:\d{2})', s)
        if m:
            synthetic = f'de segunda a sexta às {m.group(1)}h {message}'
    return parse(synthetic)


def _pause_legacy_cron(task: dict[str, Any], legacy_id: str) -> None:
    hermes = shutil.which('hermes') or str(Path.home() / '.local/bin/hermes')
    legacy_name = str(task.get('name') or '').strip()
    if not legacy_name:
        return
    try:
        subprocess.run([hermes, 'cron', 'pause', legacy_name], text=True, capture_output=True, timeout=20)
    except Exception as exc:
        _log(f'legacy_pause_failed id={legacy_id} name={legacy_name!r} error={exc}')


def migrate_legacy_reminders() -> int:
    try:
        data = json.loads(LEGACY.read_text(encoding='utf-8'))
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0

    created = 0
    fingerprints = _existing_legacy_fingerprints()
    for legacy_id, task in data.items():
        if not isinstance(task, dict) or task.get('type') != 'reminder':
            continue
        if _already_migrated(str(legacy_id)):
            _pause_legacy_cron(task, str(legacy_id))
            continue

        message = str(task.get('message') or task.get('name') or 'Lembrete').strip()
        parsed = _legacy_parse(str(task.get('schedule') or ''), message)
        if not parsed or parsed.get('needs_clarification') or not parsed.get('recurrence'):
            continue

        fingerprint = _legacy_fingerprint(message, parsed['recurrence'], parsed.get('timezone'))
        if fingerprint in fingerprints:
            _log(f'legacy_migration_duplicate_skipped id={legacy_id}')
            _pause_legacy_cron(task, str(legacy_id))
            continue

        try:
            create_schedule(
                str(task.get('name') or f'Lembrete - {message[:60]}'),
                message,
                parsed['recurrence'],
                kind='reminder',
                timezone=parsed.get('timezone'),
                source='legacy-cron-migration',
                metadata={'legacy_cron_id': str(legacy_id), 'legacy_schedule': task.get('schedule')},
            )
            fingerprints.add(fingerprint)
            _pause_legacy_cron(task, str(legacy_id))
            created += 1
        except Exception as exc:
            _log(f'legacy_migration_failed id={legacy_id} error={exc}')
    return created


def tick() -> None:
    # No automatic retry loop here. A schedule occurrence is sent at most once.
    for occ in claim_due(limit=50):
        _deliver(occ)


def main() -> int:
    if not _acquire_singleton():
        _log('time-engine duplicate process refused by singleton lock')
        print('Hermes Time Engine já está ativo; processo duplicado encerrado.', flush=True)
        return 0

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    quarantined = _quarantine_legacy_retries()
    deduplicated = _dedupe_legacy_schedules()
    migrated = migrate_legacy_reminders()
    _log(
        f'time-engine started migrated={migrated} '
        f'deduplicated_legacy={deduplicated} quarantined_retries={quarantined}'
    )
    print(
        f'Hermes Time Engine ativo; lembretes legados migrados={migrated}; '
        f'duplicados legados cancelados={deduplicated}; retries antigos bloqueados={quarantined}',
        flush=True,
    )
    while RUNNING:
        try:
            tick()
        except Exception as exc:
            _log(f'tick_error={exc!r}')
            print(f'time-engine error: {exc}', flush=True)
        time.sleep(20)
    stats = occurrence_stats()
    _log(f'time-engine stopped stats={stats}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
