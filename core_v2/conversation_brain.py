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


def _validate(data: dict[str, Any], current: str) -> dict[str, Any] | None:
    mode = _clean(data.get('mode')).casefold()
    route = _clean(data.get('route')).casefold()
    action = _clean(data.get('action')).casefold() or 'none'
    entity = _clean(data.get('entity')).casefold() or 'unknown'
    scope = _clean(data.get('scope')).casefold() or 'unknown'
    reference = _clean(data.get('reference'), 360)
    response = _clean(data.get('response'), 1200)
    rewritten = _clean(data.get('standalone_request'), 900) or current
    confidence = data.get('confidence', 0.0)

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
    period = _clean(data.get('period'), 40).casefold()
    date = _clean(data.get('date'), 40)
    hour = _to_int(data.get('hour'))
    minute = _to_int(data.get('minute'))
    if period:
        filters['period'] = period
    if date:
        filters['date'] = date
    if hour is not None:
        filters['hour'] = hour
    if minute is not None:
        filters['minute'] = minute

    ids = data.get('ids') if isinstance(data.get('ids'), list) else []
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
        'references_previous_turn': bool(data.get('references_previous_turn')),
        'reason': _clean(data.get('reason'), 180),
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


def decide(text: str, recent_context: str, llm: Callable[..., str]) -> dict[str, Any] | None:
    current = str(text or '').strip()
    if not current:
        return None

    # The tiny agent only understands intent. State lookup and execution happen later.
    recent = str(recent_context or '')[-700:]
    now = datetime.now(tz(DEFAULT_TZ)).isoformat(timespec='minutes')
    examples = select_examples(current, limit=7)

    system = (
        '/no_think\n'
        'Você é o agente operacional diário do Hermes. Classifique intenção e extraia tempo/contexto. '
        'Retorne SOMENTE um JSON compacto, sem markdown nem explicação. '
        'Nunca transforme pergunta em ação. Nunca invente IDs. Se uma ação estiver ambígua, peça o dado faltante em response. '
        'Assuntos simples de agenda/tarefa/rotina ficam em time/task/automation; pesquisa, código, explicação ou conversa geral devem ser delegados. '
        'Para delegar use a route adequada e action=answer/search, deixando response vazio. '
        'Campos: mode,route,action,entity,scope,reference,period,date,hour,minute,references_previous_turn,confidence,response,reason,standalone_request. '
        'mode=chat|query|action|followup; route=time|task|automation|finance|research|developer|devops|memory|mission|connected|assistant|chat; '
        'action=none|create|list|status|update|remove|pause|resume|run|answer|search|execute|continue|complete|reschedule; '
        'entity=day|routine|reminder|alert|event|commitment|schedule|task|automation|unknown; scope=single|selection|all|filtered|unknown; '
        'period=today|tomorrow|this_week|next_week|this_month|next_month quando aplicável.'
    )
    prompt = (
        f'AGORA:{now}\n'
        f'EXEMPLOS:\n{examples}\n'
        f'CONTEXTO:{recent or "-"}\n'
        f'MENSAGEM:{current}'
    )

    parsed = _call_once(llm, prompt, system, 128)
    return _validate(parsed, current) if parsed else None
