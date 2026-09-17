#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Callable

from daily_agent_examples import select_examples
from time_store import DEFAULT_TZ, tz

_ALLOWED_MODES = {'chat', 'query', 'action', 'followup'}
_ALLOWED_ROUTES = {
    'time', 'task', 'automation', 'finance', 'research', 'developer', 'devops',
    'memory', 'mission', 'connected', 'assistant', 'chat',
}
_ALLOWED_ACTIONS = {
    'none', 'create', 'list', 'status', 'update', 'remove', 'pause',
    'resume', 'run', 'answer', 'search', 'execute', 'continue', 'complete', 'reschedule',
}
_ALLOWED_SCOPES = {'single', 'selection', 'all', 'filtered', 'unknown'}
_ALLOWED_ENTITIES = {
    'day', 'routine', 'reminder', 'alert', 'event', 'commitment', 'schedule',
    'task', 'automation', 'unknown',
}


def _extract_json(raw: str) -> dict[str, Any] | None:
    text = str(raw or '').strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _clean(value: Any, limit: int = 900) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit]


def _to_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() != '' else None
    except Exception:
        return None


def _pick(data: dict[str, Any], long_key: str, short_key: str, default: Any = None) -> Any:
    if long_key in data:
        return data.get(long_key)
    return data.get(short_key, default)


def _validate(data: dict[str, Any], current: str) -> dict[str, Any] | None:
    # Aceita tanto o contrato longo antigo quanto o contrato curto usado pelo
    # modelo de 0.6B. O executor interno continua recebendo o formato completo.
    mode = _clean(_pick(data, 'mode', 'm')).casefold()
    route = _clean(_pick(data, 'route', 'r')).casefold()
    action = _clean(_pick(data, 'action', 'a')).casefold() or 'none'
    entity = _clean(_pick(data, 'entity', 'e')).casefold() or 'unknown'
    scope = _clean(_pick(data, 'scope', 's')).casefold() or 'unknown'
    reference = _clean(_pick(data, 'reference', 'ref'), 360)
    response = _clean(_pick(data, 'response', 'resp'), 1200)
    rewritten = _clean(_pick(data, 'standalone_request', 'q'), 900) or current
    confidence = _pick(data, 'confidence', 'c', 0.0)

    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except Exception:
        confidence = 0.0

    if mode not in _ALLOWED_MODES or route not in _ALLOWED_ROUTES or action not in _ALLOWED_ACTIONS:
        return None
    if entity not in _ALLOWED_ENTITIES:
        entity = 'unknown'
    if scope not in _ALLOWED_SCOPES:
        scope = 'unknown'

    mutating = action in {'create', 'update', 'remove', 'pause', 'resume', 'run', 'execute', 'complete', 'reschedule'}
    if mutating and mode not in {'action', 'followup'}:
        return None

    filters: dict[str, Any] = {}
    period = _clean(_pick(data, 'period', 'p'), 40).casefold()
    date = _clean(_pick(data, 'date', 'd'), 40)
    hour = _to_int(_pick(data, 'hour', 'h'))
    minute = _to_int(_pick(data, 'minute', 'n'))
    if period:
        filters['period'] = period
    if date:
        filters['date'] = date
    if hour is not None:
        filters['hour'] = hour
    if minute is not None:
        filters['minute'] = minute

    raw_ids = _pick(data, 'ids', 'i', [])
    ids = raw_ids if isinstance(raw_ids, list) else []
    clean_ids: list[str] = []
    for value in ids[:20]:
        ref = _clean(value, 64)
        if re.fullmatch(r'[0-9a-fA-F]{6,32}', ref):
            clean_ids.append(ref)

    return {
        'mode': mode,
        'route': route,
        'action': action,
        'standalone_request': rewritten,
        'response': response,
        'confidence': confidence,
        'references_previous_turn': bool(_pick(data, 'references_previous_turn', 'prev', False)),
        'reason': _clean(_pick(data, 'reason', 'why'), 180),
        'target': {
            'entity': entity,
            'scope': scope,
            'reference': reference,
            'ids': clean_ids,
            'filters': filters,
        },
    }


def _call_once(llm: Callable[..., str], prompt: str, system: str, max_tokens: int) -> dict[str, Any] | None:
    try:
        raw = llm(prompt, system=system, max_tokens=max_tokens)
    except Exception:
        return None
    return _extract_json(raw)


def _compact_examples(text: str) -> str:
    lines: list[str] = []
    for raw in select_examples(text, limit=3).splitlines():
        try:
            item = json.loads(raw)
        except Exception:
            continue
        compact = {
            'u': item.get('u'),
            'm': item.get('mode'),
            'r': item.get('route'),
            'a': item.get('action'),
            'e': item.get('entity'),
            's': item.get('scope'),
        }
        lines.append(json.dumps(compact, ensure_ascii=False, separators=(',', ':')))
    return '\n'.join(lines[:3])


def decide(text: str, recent_context: str, llm: Callable[..., str]) -> dict[str, Any] | None:
    current = str(text or '').strip()
    if not current:
        return None

    # O 0.6B deve classificar, não raciocinar sobre todo o estado. Mantemos só
    # um pedaço mínimo da conversa para pronomes/follow-ups e três exemplos
    # semanticamente próximos. Isso reduz o prompt de ~780 tokens para poucas
    # centenas sem transformar exemplos em regras hardcoded.
    recent = str(recent_context or '')[-260:]
    now = datetime.now(tz(DEFAULT_TZ)).isoformat(timespec='minutes')
    examples = _compact_examples(current)

    system = (
        '/no_think\n'
        'Só JSON. Entenda PT-BR informal e classifique a intenção. '
        'Nunca transforme pergunta em ação e nunca invente ID. '
        'Use chaves curtas: m,r,a,e,s,ref,p,d,h,n,prev,c,resp,q. '
        'm=chat|query|action|followup; '
        'r=time|task|automation|finance|research|developer|devops|memory|mission|connected|assistant|chat; '
        'a=none|create|list|status|update|remove|pause|resume|run|answer|search|execute|continue|complete|reschedule; '
        'e=day|routine|reminder|alert|event|commitment|schedule|task|automation|unknown; '
        's=single|selection|all|filtered|unknown. '
        'p=today|tomorrow|this_week|next_week|this_month|next_month quando couber. '
        'Se faltar dado para uma ação, a=answer,r=chat e resp pergunta só o necessário.'
    )
    prompt = (
        f'T:{now}\n'
        f'EX:\n{examples}\n'
        f'CTX:{recent or "-"}\n'
        f'U:{current}'
    )

    parsed = _call_once(llm, prompt, system, 96)
    return _validate(parsed, current) if parsed else None
