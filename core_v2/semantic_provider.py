from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from telemetry import emit

_STATE = Path(__file__).resolve().parent / 'state' / 'daily_agent_health.json'
_ENV_FILES = [
    Path.home() / '.config' / 'hermes' / 'daily-agent.env',
    Path.home() / '.hermes' / '.env',
]
_DEFAULT_BASE_URL = 'http://127.0.0.1:8087/v1'
_DEFAULT_MODEL = 'Qwen3-0.6B-Q4_0.gguf'


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
    # Strictly local: no remote API keys or remote fallback are ever considered here.
    base_url = (_env('HERMES_DAILY_AGENT_BASE_URL') or _DEFAULT_BASE_URL).rstrip('/')
    model = _env('HERMES_DAILY_AGENT_MODEL') or _DEFAULT_MODEL
    return base_url, model, None, 'daily_agent_local'


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
    return float(_read_health().get('open_until') or 0) > time.time()


def _mark_success(elapsed_ms: float) -> None:
    _write_health({'failures': 0, 'open_until': 0, 'last_ok_at': int(time.time()), 'elapsed_ms': round(elapsed_ms, 1)})


def _mark_failure(error: str) -> None:
    state = _read_health()
    failures = int(state.get('failures') or 0) + 1
    cooldown = 20 if failures >= 2 else 0
    _write_health({
        'failures': failures,
        'open_until': int(time.time()) + cooldown if cooldown else 0,
        'last_error_at': int(time.time()),
        'error': error[:300],
    })


def _timeout_seconds() -> float:
    return max(1.0, min(6.0, float(_env('HERMES_DAILY_AGENT_TIMEOUT') or 3.5)))


def _request(prompt: str, system: str, max_tokens: int) -> str:
    base_url, model, _key, provider_kind = _provider()
    timeout_seconds = _timeout_seconds()
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0,
        'max_tokens': min(max(64, int(max_tokens or 128)), 144),
    }
    timeout = httpx.Timeout(connect=1.0, read=timeout_seconds, write=timeout_seconds, pool=1.0)
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout, headers={'Content-Type': 'application/json'}) as client:
            response = client.post(f'{base_url}/chat/completions', json=payload)
            response.raise_for_status()
            data = response.json()
        result = str((((data.get('choices') or [{}])[0].get('message') or {}).get('content')) or '').strip()
        elapsed_ms = (time.perf_counter() - started) * 1000
        if not result:
            raise RuntimeError('daily agent returned empty content')
        _mark_success(elapsed_ms)
        emit('brain.provider', ok=True, provider=provider_kind, model=model, elapsed_ms=elapsed_ms, prompt_chars=len(prompt), output_chars=len(result))
        return result
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        _mark_failure(str(exc))
        emit('brain.provider', ok=False, provider=provider_kind, model=model, elapsed_ms=elapsed_ms, error=str(exc)[:300])
        raise


def llm(prompt: str, system: str | None = None, max_tokens: int | None = None) -> str:
    if _circuit_open():
        raise TimeoutError('daily local semantic agent circuit open')
    return _request(prompt, system or '/no_think\nRetorne somente JSON válido.', max_tokens or 128)


def health() -> dict[str, Any]:
    primary = _provider()
    return {
        'primary': {'base_url': primary[0], 'model': primary[1], 'kind': primary[3]},
        'fallback': None,
        'remote_enabled': False,
        'circuit_open': _circuit_open(),
        'state': _read_health(),
        'timeout_seconds': _timeout_seconds(),
    }
