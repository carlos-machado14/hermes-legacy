from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path.home() / '.hermes' / 'core-v2'
STATE_DIR = ROOT / 'state'
CHANNEL_FILE = STATE_DIR / 'channel_state.json'
ENV_FILE = Path.home() / '.hermes' / '.env'


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


def channel() -> dict[str, Any] | None:
    try:
        data = json.loads(CHANNEL_FILE.read_text(encoding='utf-8'))
    except Exception:
        return None
    if not isinstance(data, dict) or not str(data.get('chat_id') or '').strip():
        return None
    return data


def split_message(text: str, limit: int = 3600) -> list[str]:
    raw = str(text or '').strip()
    if not raw:
        return []
    chunks: list[str] = []
    while len(raw) > limit:
        cut = raw.rfind('\n\n', 0, limit)
        if cut < limit // 2:
            cut = raw.rfind('\n', 0, limit)
        if cut < limit // 2:
            cut = raw.rfind(' ', 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(raw[:cut].strip())
        raw = raw[cut:].lstrip()
    if raw:
        chunks.append(raw)
    return chunks


def _ambiguous_transport_error(exc: Exception) -> bool:
    """True when Telegram may have accepted the message before the client errored.

    Telegram's Bot API does not expose an idempotency key for sendMessage. Retrying
    a read/write/protocol failure can therefore produce duplicate notifications.
    """
    return isinstance(
        exc,
        (
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.ReadError,
            httpx.WriteError,
            httpx.RemoteProtocolError,
        ),
    )


def send_telegram(text: str, *, chat_id: str | None = None, attempts: int = 3) -> tuple[bool, str]:
    token = _env('TELEGRAM_BOT_TOKEN')
    ch = channel() or {}
    target = str(chat_id or ch.get('chat_id') or '').strip()
    if not token:
        return False, 'telegram_token_missing'
    if not target:
        return False, 'telegram_chat_missing'
    chunks = split_message(text)
    if not chunks:
        return False, 'empty_message'

    last_error = ''
    for chunk in chunks:
        delivered = False
        for attempt in range(1, max(1, attempts) + 1):
            try:
                with httpx.Client(timeout=20) as client:
                    r = client.post(
                        f'https://api.telegram.org/bot{token}/sendMessage',
                        json={'chat_id': target, 'text': chunk},
                    )
                if r.is_success:
                    delivered = True
                    break

                last_error = f'HTTP {r.status_code}: {r.text[-300:]}'
                # 4xx (except rate limit) are deterministic failures. Repeating them
                # only wastes attempts and cannot make the request valid.
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    return False, last_error
            except Exception as exc:
                if _ambiguous_transport_error(exc):
                    # Do not retry inside this call: Telegram may already have
                    # accepted sendMessage even though the response was lost.
                    return False, f'ambiguous_delivery:{type(exc).__name__}:{exc}'
                last_error = f'{type(exc).__name__}:{exc}'

            if attempt < attempts:
                time.sleep(min(2 ** attempt, 5))

        if not delivered:
            return False, last_error or 'telegram_delivery_failed'
    return True, ''
