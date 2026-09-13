#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from decision_log import recent as recent_decisions, record
from goal_manager import list_goals
from proactive_engine import daily_brief, weekly_review, recommendation
from proactive_settings import load as load_settings
from task_manager import list_tasks

ROOT = Path.home() / '.hermes/core-v2'
STATE_DIR = ROOT / 'state'
CHANNEL_FILE = STATE_DIR / 'channel_state.json'
RUNTIME_FILE = STATE_DIR / 'autonomous_runtime.json'
ENV_FILE = Path.home() / '.hermes/.env'


def _read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else fallback
    except Exception:
        return fallback


def _write_json(path: Path, data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _env(name: str) -> str:
    value = (os.getenv(name) or '').strip()
    if value:
        return value
    try:
        for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
            raw = line.strip()
            if not raw or raw.startswith('#') or '=' not in raw:
                continue
            key, val = raw.split('=', 1)
            if key.strip() == name:
                return val.strip().strip('"').strip("'")
    except Exception:
        pass
    return ''


def _channel() -> dict[str, Any] | None:
    data = _read_json(CHANNEL_FILE, {})
    if str(data.get('platform') or '').lower() != 'telegram':
        return None
    if not str(data.get('chat_id') or '').strip():
        return None
    return data


def _send(text: str) -> bool:
    token = _env('TELEGRAM_BOT_TOKEN')
    channel = _channel()
    if not token or not channel or not text.strip():
        return False
    try:
        with httpx.Client(timeout=15) as client:
            r = client.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': str(channel['chat_id']), 'text': text[:3900]},
            )
            return r.is_success
    except Exception:
        return False


def _quiet(settings: dict[str, Any], now: datetime) -> bool:
    start = int(settings.get('quiet_start_hour', 22)) % 24
    end = int(settings.get('quiet_end_hour', 7)) % 24
    h = now.hour
    if start == end:
        return False
    return h >= start or h < end if start > end else start <= h < end


def _last_progress_ts() -> int:
    rows = recent_decisions(100)
    progress_kinds = {'task_completed', 'goal_progress', 'goal_completed', 'next_action', 'decision'}
    stamps = [int(x.get('ts') or 0) for x in rows if x.get('kind') in progress_kinds]
    return max(stamps, default=0)


def _overdue_high_tasks() -> list[dict[str, Any]]:
    today = datetime.now().date()
    out: list[dict[str, Any]] = []
    for task in list_tasks(status='todo'):
        if task.get('priority') != 'high' or not task.get('due'):
            continue
        raw = str(task.get('due')).strip()
        try:
            due = datetime.fromisoformat(raw).date()
        except Exception:
            continue
        if due < today:
            out.append(task)
    return out


def _slot(runtime: dict[str, Any], key: str, stamp: str) -> bool:
    return runtime.get(key) != stamp


def _mark(runtime: dict[str, Any], key: str, stamp: str) -> None:
    runtime[key] = stamp
    runtime['updated_at'] = int(time.time())
    _write_json(RUNTIME_FILE, runtime)


def tick() -> None:
    settings = load_settings()
    if not settings.get('enabled'):
        return
    if not _channel() or not _env('TELEGRAM_BOT_TOKEN'):
        return

    now = datetime.now()
    runtime = _read_json(RUNTIME_FILE, {})
    day = now.strftime('%Y-%m-%d')
    week = now.strftime('%G-W%V')

    morning_hour = int(settings.get('morning_hour', 8)) % 24
    evening_hour = int(settings.get('evening_hour', 19)) % 24
    weekly_day = int(settings.get('weekly_review_weekday', 6)) % 7
    weekly_hour = int(settings.get('weekly_review_hour', 18)) % 24

    if now.hour == morning_hour and _slot(runtime, 'morning_sent', day):
        text = '☀️ Hermes — plano do dia\n\n' + daily_brief()
        if _send(text):
            record('proactive_brief', 'Brief da manhã enviado.')
            _mark(runtime, 'morning_sent', day)
        return

    if now.weekday() == weekly_day and now.hour == weekly_hour and _slot(runtime, 'weekly_sent', week):
        text = '📊 Hermes — revisão semanal\n\n' + weekly_review()
        if _send(text):
            record('proactive_review', 'Revisão semanal enviada.')
            _mark(runtime, 'weekly_sent', week)
        return

    if now.hour == evening_hour and _slot(runtime, 'evening_sent', day):
        text = '🌙 Hermes — fechamento do dia\n\n' + weekly_review()
        if _send(text):
            record('proactive_review', 'Fechamento do dia enviado.')
            _mark(runtime, 'evening_sent', day)
        return

    if _quiet(settings, now):
        return

    overdue = _overdue_high_tasks()
    if overdue and _slot(runtime, 'overdue_alert', day):
        lines = ['⚠️ Hermes — há tarefas importantes atrasadas:']
        for task in overdue[:5]:
            lines.append(f"- {task.get('title')}")
        lines.append('\nQuer que eu reorganize suas prioridades?')
        if _send('\n'.join(lines)):
            record('proactive_alert', f'{len(overdue)} tarefa(s) de alta prioridade atrasada(s).')
            _mark(runtime, 'overdue_alert', day)
        return

    goals = list_goals(include_done=False)
    stall_hours = max(1, int(settings.get('stall_hours', 24)))
    last_progress = _last_progress_ts()
    if goals and last_progress and time.time() - last_progress >= stall_hours * 3600:
        stall_stamp = datetime.now().strftime('%Y-%m-%d')
        if _slot(runtime, 'stall_alert', stall_stamp):
            text = '🧭 Hermes — percebi que seus objetivos estão sem avanço recente.\n\n' + recommendation()
            if _send(text):
                record('proactive_alert', 'Objetivo sem avanço recente; recomendação enviada.')
                _mark(runtime, 'stall_alert', stall_stamp)


def main() -> int:
    print('Hermes Core v3.3 autonomous service ativo', flush=True)
    while True:
        try:
            tick()
        except Exception as exc:
            print(f'autonomous tick error: {exc}', flush=True)
        time.sleep(60)


if __name__ == '__main__':
    raise SystemExit(main())
