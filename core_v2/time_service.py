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
    for item in list_schedules(limit=500):
        meta = item.get('metadata') or {}
        if str(meta.get('legacy_cron_id') or '') == legacy_id:
            return True
    return False


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


def migrate_legacy_reminders() -> int:
    try:
        data = json.loads(LEGACY.read_text(encoding='utf-8'))
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0
    created = 0
    for legacy_id, task in data.items():
        if not isinstance(task, dict) or task.get('type') != 'reminder' or _already_migrated(str(legacy_id)):
            continue
        message = str(task.get('message') or task.get('name') or 'Lembrete').strip()
        parsed = _legacy_parse(str(task.get('schedule') or ''), message)
        if not parsed or parsed.get('needs_clarification') or not parsed.get('recurrence'):
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
            hermes = shutil.which('hermes') or str(Path.home() / '.local/bin/hermes')
            legacy_name = str(task.get('name') or '').strip()
            if legacy_name:
                try:
                    subprocess.run([hermes, 'cron', 'pause', legacy_name], text=True, capture_output=True, timeout=20)
                except Exception as exc:
                    _log(f'legacy_pause_failed id={legacy_id} name={legacy_name!r} error={exc}')
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
    migrated = migrate_legacy_reminders()
    _log(f'time-engine started migrated={migrated} quarantined_retries={quarantined}')
    print(
        f'Hermes Time Engine ativo; lembretes legados migrados={migrated}; '
        f'retries antigos bloqueados={quarantined}',
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
