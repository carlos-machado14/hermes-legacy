from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx


def _env(name: str) -> str:
    value = (os.getenv(name) or '').strip()
    if value:
        return value
    for path in (
        Path.home() / '.config' / 'hermes' / 'core-api.env',
        Path.home() / '.hermes' / '.env',
    ):
        try:
            for line in path.read_text(encoding='utf-8').splitlines():
                raw = line.strip()
                if not raw or raw.startswith('#') or '=' not in raw:
                    continue
                key, val = raw.split('=', 1)
                if key.strip() == name:
                    return val.strip().strip('"').strip("'")
        except Exception:
            pass
    return ''


def identity() -> dict[str, str]:
    return {
        'channel': (os.getenv('HERMES_CHANNEL_PLATFORM') or '').strip().lower(),
        'externalUserId': (os.getenv('HERMES_CHANNEL_USER_ID') or '').strip(),
        'chatId': (os.getenv('HERMES_CHANNEL_CHAT_ID') or '').strip(),
    }


def configured() -> bool:
    ident = identity()
    return bool(
        _env('FREUD_CHANNEL_BROKER_URL')
        and _env('FREUD_CHANNEL_BROKER_TOKEN')
        and ident['channel']
        and ident['externalUserId']
    )


def _post(path: str, payload: dict[str, Any], timeout: float = 20.0) -> dict[str, Any]:
    base = _env('FREUD_CHANNEL_BROKER_URL').rstrip('/')
    token = _env('FREUD_CHANNEL_BROKER_TOKEN')
    if not base or not token:
        return {'ok': False, 'error': 'freud_broker_not_configured'}
    try:
        response = httpx.post(
            f'{base}/{path.lstrip("/")}',
            json=payload,
            headers={'Authorization': f'Bearer {token}'},
            timeout=timeout,
        )
        try:
            data = response.json()
        except Exception:
            data = {'error': response.text[:1000]}
        if response.status_code >= 400:
            return {
                'ok': False,
                'status': response.status_code,
                'error': data.get('message') or data.get('error') or f'http_{response.status_code}',
                'detail': data,
            }
        if isinstance(data, dict):
            return data
        return {'ok': True, 'data': data}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}


def link(code: str) -> dict[str, Any]:
    ident = identity()
    return _post('link', {**ident, 'code': code.strip().upper()})


def catalog() -> dict[str, Any]:
    ident = identity()
    return _post('catalog', {
        'channel': ident['channel'],
        'externalUserId': ident['externalUserId'],
    })


def execute(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    ident = identity()
    return _post('tool', {
        'channel': ident['channel'],
        'externalUserId': ident['externalUserId'],
        'name': name,
        'arguments': arguments or {},
    }, timeout=35.0)


def status() -> dict[str, Any]:
    ident = identity()
    return {
        'configured': configured(),
        'channel': ident['channel'] or None,
        'externalUserId': ident['externalUserId'] or None,
        'brokerUrlConfigured': bool(_env('FREUD_CHANNEL_BROKER_URL')),
        'tokenConfigured': bool(_env('FREUD_CHANNEL_BROKER_TOKEN')),
    }
