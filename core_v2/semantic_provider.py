from __future__ import annotations

import hashlib
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
_EXISTING_ROUTER_KEY = 'HERMES_CUSTOM_API_ROUTER_NGCTECH_COM_BR_API_KEY'
_DEFAULT_ROUTER_URL = 'https://api-router.ngctech.com.br/v1'
_DEFAULT_ROUTER_MODEL = 'combo-free'


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
    # Configuração explícita sempre vence.
    base_url = _env('HERMES_BRAIN_BASE_URL').rstrip('/')
    model = _env('HERMES_BRAIN_MODEL')
    key = _env('HERMES_BRAIN_API_KEY') or None
    if base_url and model:
        return base_url, model, key, 'brain'

    # Reaproveita o provider já configurado no Hermes sem copiar/expor a chave.
    router_key = _env(_EXISTING_ROUTER_KEY) or None
    if router_key:
        router_url = (_env('HERMES_BRAIN_ROUTER_URL') or _DEFAULT_ROUTER_URL).rstrip('/')
        router_model = _env('HERMES_BRAIN_ROUTER_MODEL') or _DEFAULT_ROUTER_MODEL
        return router_url, router_model, router_key, 'omniroute'

    return hermes_core.BASE_URL, hermes_core.MODEL, None, 'local'


def _fallback_provider() -> tuple[str, str, str | None, str] | None:
    base_url = _env('HERMES_BRAIN_FALLBACK_BASE_URL').rstrip('/')
    model = _env('HERMES_BRAIN_FALLBACK_MODEL')
    key = _env('HERMES_BRAIN_FALLBACK_API_KEY') or None
    if base_url and model:
        return base_url, model, key, 'brain_fallback'

    # Quando OmniRoute é o primário, o Qwen local vira fallback real.
    primary = _provider()
    if primary[3] == 'omniroute':
        return hermes_core.BASE_URL, hermes_core.MODEL, None, 'local_fallback'
    return None


def _provider_id(endpoint: tuple[str, str, str | None, str]) -> str:
    base_url, model, _key, provider_kind = endpoint
    raw = f'{provider_kind}|{base_url}|{model}'.encode('utf-8')
    return hashlib.sha1(raw).hexdigest()[:12]


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


def _provider_health(endpoint: tuple[str, str, str | None, str]) -> dict[str, Any]:
    state = _read_health()
    providers = state.get('providers') if isinstance(state.get('providers'), dict) else {}
    item = providers.get(_provider_id(endpoint))
    return item if isinstance(item, dict) else {}


def _circuit_open(endpoint: tuple[str, str, str | None, str]) -> bool:
    return float(_provider_health(endpoint).get('open_until') or 0) > time.time()


def _save_provider_health(endpoint: tuple[str, str, str | None, str], item: dict[str, Any]) -> None:
    state = _read_health()
    providers = state.get('providers') if isinstance(state.get('providers'), dict) else {}
    providers[_provider_id(endpoint)] = item
    state['providers'] = providers
    _write_health(state)


def _mark_success(endpoint: tuple[str, str, str | None, str], elapsed_ms: float) -> None:
    _save_provider_health(endpoint, {
        'failures': 0,
        'open_until': 0,
        'last_ok_at': int(time.time()),
        'provider': endpoint[3],
        'model': endpoint[1],
        'elapsed_ms': round(elapsed_ms, 1),
    })


def _mark_failure(endpoint: tuple[str, str, str | None, str], error: str) -> None:
    current = _provider_health(endpoint)
    failures = int(current.get('failures') or 0) + 1
    cooldown = 30 if failures >= 2 else 0
    _save_provider_health(endpoint, {
        'failures': failures,
        'open_until': int(time.time()) + cooldown if cooldown else 0,
        'last_error_at': int(time.time()),
        'provider': endpoint[3],
        'model': endpoint[1],
        'error': error[:300],
    })


def _timeout_for(endpoint: tuple[str, str, str | None, str]) -> float:
    default = 7.0 if endpoint[3] in {'local', 'local_fallback'} else 10.0
    return max(2.0, min(15.0, float(_env('HERMES_BRAIN_TIMEOUT') or default)))


def _request(endpoint: tuple[str, str, str | None, str], prompt: str, system: str, max_tokens: int) -> str:
    base_url, model, api_key, provider_kind = endpoint
    timeout_seconds = _timeout_for(endpoint)
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
        'max_tokens': min(max(64, int(max_tokens or 160)), 180),
    }
    timeout = httpx.Timeout(connect=min(3.0, timeout_seconds), read=timeout_seconds, write=timeout_seconds, pool=3.0)
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
        _mark_success(endpoint, elapsed_ms)
        emit('brain.provider', ok=True, provider=provider_kind, model=model, elapsed_ms=elapsed_ms, prompt_chars=len(prompt), output_chars=len(result))
        return result
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        _mark_failure(endpoint, str(exc))
        emit('brain.provider', ok=False, provider=provider_kind, model=model, elapsed_ms=elapsed_ms, error=str(exc)[:300])
        raise


def llm(prompt: str, system: str | None = None, max_tokens: int | None = None) -> str:
    system = system or '/no_think\nRetorne somente JSON válido.'
    primary = _provider()
    if not _circuit_open(primary):
        try:
            return _request(primary, prompt, system, max_tokens or 160)
        except Exception:
            pass

    fallback = _fallback_provider()
    if fallback is not None and not _circuit_open(fallback):
        try:
            return _request(fallback, prompt, system, max_tokens or 160)
        except Exception:
            pass

    raise TimeoutError('semantic provider unavailable')


def _public(endpoint: tuple[str, str, str | None, str] | None) -> dict[str, Any] | None:
    if endpoint is None:
        return None
    return {
        'base_url': endpoint[0],
        'model': endpoint[1],
        'kind': endpoint[3],
        'has_api_key': bool(endpoint[2]),
        'circuit_open': _circuit_open(endpoint),
        'state': _provider_health(endpoint),
        'timeout_seconds': _timeout_for(endpoint),
    }


def health() -> dict[str, Any]:
    primary = _provider()
    fallback = _fallback_provider()
    return {
        'primary': _public(primary),
        'fallback': _public(fallback),
    }
