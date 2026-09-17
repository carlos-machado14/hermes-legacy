from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

import hermes_core
from telemetry import emit

_STATE = Path(__file__).resolve().parent / 'state' / 'semantic_provider_health.json'
_ENV_FILES = [
    Path.home() / '.config' / 'hermes' / 'brain.env',
    Path.home() / '.hermes' / '.env',
]


def _env(name: str) -> str:
    direct = str(os.getenv(name) or '').strip()
    if direct:
        return direct
    for path in _ENV_FILES:
        try:
            for line in path.read_text(encoding='utf-8').splitlines():
                raw = line.strip()
                if not raw or raw.startswith('#') or '=' not in raw:
                    continue
                key, value = raw.split('=', 1)
                if key.strip() == name:
                    return value.strip().strip('"').strip("'")
        except Exception:
            continue
    return ''


def _provider() -> tuple[str, str, str | None, str]:
    base_url = _env('HERMES_BRAIN_BASE_URL').rstrip('/')
    model = _env('HERMES_BRAIN_MODEL')
    key = _env('HERMES_BRAIN_API_KEY') or None
    if base_url and model:
        return base_url, model, key, 'brain'
    return hermes_core.BASE_URL, hermes_core.MODEL, None, 'local'


def _fallback_provider() -> tuple[str, str, str | None, str] | None:
    base_url = _env('HERMES_BRAIN_FALLBACK_BASE_URL').rstrip('/')
    model = _env('HERMES_BRAIN_FALLBACK_MODEL')
    key = _env('HERMES_BRAIN_FALLBACK_API_KEY') or None
    if base_url and model:
        return base_url, model, key, 'brain_fallback'
    return None


def _read_health() -> dict[str, Any]:
    try:
        data = json.loads(_STATE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_health(data: dict[str, Any]) -> None:
    try:
        _STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATE.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        tmp.replace(_STATE)
    except Exception:
        pass


def _circuit_open() -> bool:
    state = _read_health()
    return float(state.get('open_until') or 0) > time.time()


def _mark_success(provider: str, elapsed_ms: float) -> None:
    _write_health({'failures': 0, 'open_until': 0, 'last_ok_at': int(time.time()), 'provider': provider, 'elapsed_ms': round(elapsed_ms, 1)})


def _mark_failure(provider: str, error: str) -> None:
    state = _read_health()
    failures = int(state.get('failures') or 0) + 1
    cooldown = 30 if failures >= 2 else 0
    _write_health({
        'failures': failures,
        'open_until': int(time.time()) + cooldown if cooldown else 0,
        'last_error_at': int(time.time()),
        'provider': provider,
        'error': error[:300],
    })


def _request(endpoint: tuple[str, str, str | None, str], prompt: str, system: str, max_tokens: int) -> str:
    base_url, model, api_key, provider_kind = endpoint
    timeout_seconds = max(1.5, min(8.0, float(_env('HERMES_BRAIN_TIMEOUT') or 4.0)))
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0,
        'max_tokens': min(max(80, int(max_tokens or 180)), 240),
    }
    timeout = httpx.Timeout(connect=min(2.0, timeout_seconds), read=timeout_seconds, write=timeout_seconds, pool=2.0)
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout, headers=headers) as client:
            response = client.post(f'{base_url}/chat/completions', json=payload)
            response.raise_for_status()
            data = response.json()
        result = str((((data.get('choices') or [{}])[0].get('message') or {}).get('content')) or '').strip()
        elapsed_ms = (time.perf_counter() - started) * 1000
        if not result:
            raise RuntimeError('semantic provider returned empty content')
        _mark_success(provider_kind, elapsed_ms)
        emit('brain.provider', ok=True, provider=provider_kind, model=model, elapsed_ms=elapsed_ms, prompt_chars=len(prompt), output_chars=len(result))
        return result
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        _mark_failure(provider_kind, str(exc))
        emit('brain.provider', ok=False, provider=provider_kind, model=model, elapsed_ms=elapsed_ms, error=str(exc)[:300])
        raise


def llm(prompt: str, system: str | None = None, max_tokens: int | None = None) -> str:
    system = system or 'Retorne somente JSON válido.'
    if not _circuit_open():
        try:
            return _request(_provider(), prompt, system, max_tokens or 180)
        except Exception:
            pass
    fallback = _fallback_provider()
    if fallback is not None:
        return _request(fallback, prompt, system, max_tokens or 180)
    raise TimeoutError('semantic provider unavailable')


def health() -> dict[str, Any]:
    primary = _provider()
    fallback = _fallback_provider()
    state = _read_health()
    return {
        'primary': {'base_url': primary[0], 'model': primary[1], 'kind': primary[3]},
        'fallback': {'base_url': fallback[0], 'model': fallback[1], 'kind': fallback[3]} if fallback else None,
        'circuit_open': _circuit_open(),
        'state': state,
    }
