from __future__ import annotations

import json
import os
import re
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

_CLASSIFIER_SYSTEM = '''/no_think
Classifique a intenção em PT-BR. Responda SOMENTE A|E|S|M|R.
A ação: L=listar C=criar R=remover U=alterar P=pausar V=retomar X=executar D=concluir G=reagendar N=responder H=buscar S=status.
E entidade: A=agenda/dia M=lembrete L=alerta E=evento C=compromisso R=rotina T=tarefa S=agenda inteira O=outro.
S escopo: 1=um A=todos F=filtrado P=seleção/contexto U=incerto.
M modo: Q=pergunta A=ação F=continuação C=conversa.
R rota: T=tempo/agenda K=tarefa U=automação S=assistente W=pesquisa D=desenvolvimento O=devops M=memória F=finanças C=conversa.
Pergunta nunca vira ação. Se não souber use N|O|U|C|S.
Exemplos:
o que tenho sábado => L|A|F|Q|T
me lembra amanhã 10h de revisar => C|M|1|A|T
cancela todos meus compromissos da agenda, quero resetar => R|S|A|A|T
terminei a tarefa do contrato => D|T|F|A|K
procura as notícias de hoje => H|O|U|Q|W'''


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
    cooldown = 5 if failures >= 3 else 0
    _write_health({
        'failures': failures,
        'open_until': int(time.time()) + cooldown if cooldown else 0,
        'last_error_at': int(time.time()),
        'error': error[:300],
    })


def _timeout_seconds() -> float:
    return max(2.0, min(10.0, float(_env('HERMES_DAILY_AGENT_TIMEOUT') or 6.0)))


def classify(text: str, recent_context: str = '') -> str:
    """Classifica intenção com saída mínima, sempre no modelo local."""
    if _circuit_open():
        raise TimeoutError('daily local semantic agent circuit open')

    base_url, model, _key, provider_kind = _provider()
    timeout_seconds = _timeout_seconds()
    recent = re.sub(r'\s+', ' ', str(recent_context or '')).strip()[-100:]
    current = re.sub(r'\s+', ' ', str(text or '')).strip()[:700]
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': _CLASSIFIER_SYSTEM},
            {'role': 'user', 'content': f'/no_think\nC:{recent or "-"}\nU:{current}\nR:'},
        ],
        'temperature': 0,
        'max_tokens': 12,
        'stop': ['\n'],
        # Builds antigos do llama.cpp/Qwen3 respeitam o kwarg por request;
        # builds novos usam os flags do servidor definidos pelo instalador.
        'chat_template_kwargs': {'enable_thinking': False},
    }
    timeout = httpx.Timeout(connect=1.0, read=timeout_seconds, write=timeout_seconds, pool=1.0)
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout, headers={'Content-Type': 'application/json'}) as client:
            response = client.post(f'{base_url}/chat/completions', json=payload)
            response.raise_for_status()
            data = response.json()
        message = ((data.get('choices') or [{}])[0].get('message') or {})
        result = str(message.get('content') or '').strip()
        elapsed_ms = (time.perf_counter() - started) * 1000
        if not result:
            reasoning = str(message.get('reasoning_content') or '').strip()
            if reasoning:
                raise RuntimeError('daily classifier returned reasoning only')
            raise RuntimeError('daily classifier returned empty content')
        if '<think' in result.casefold() or result.casefold().startswith('think'):
            raise RuntimeError('daily classifier thinking mode is still enabled')
        if not re.search(r'[LCRUPVXDGHNS]\s*\|', result.upper()):
            raise RuntimeError(f'daily classifier invalid label: {result[:80]}')
        _mark_success(elapsed_ms)
        emit('brain.provider', ok=True, provider=provider_kind, model=model, elapsed_ms=elapsed_ms,
             prompt_chars=len(current) + len(recent), output_chars=len(result), mode='label_classifier')
        return result
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        _mark_failure(str(exc))
        emit('brain.provider', ok=False, provider=provider_kind, model=model, elapsed_ms=elapsed_ms,
             error=str(exc)[:300], mode='label_classifier')
        raise


def llm(prompt: str, system: str | None = None, max_tokens: int | None = None) -> str:
    return classify(prompt, '')


def health() -> dict[str, Any]:
    primary = _provider()
    return {
        'primary': {'base_url': primary[0], 'model': primary[1], 'kind': primary[3]},
        'fallback': None,
        'remote_enabled': False,
        'classifier': 'compact_labels_v1',
        'circuit_open': _circuit_open(),
        'state': _read_health(),
        'timeout_seconds': _timeout_seconds(),
    }
