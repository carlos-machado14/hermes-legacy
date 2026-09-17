#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Callable

from agent_state import compact as operational_state, refresh as refresh_agent_state
from task_manager import list_tasks
from time_store import DEFAULT_TZ, list_schedules, tz

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


def _clean(value: Any, limit: int = 1600) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit]


def _clean_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:40]:
        ref = _clean(item, 64)
        if re.fullmatch(r'[0-9a-fA-F]{6,32}', ref) and ref not in out:
            out.append(ref)
    return out


def _validate(data: dict[str, Any], current: str) -> dict[str, Any] | None:
    mode = _clean(data.get('mode')).casefold()
    route = _clean(data.get('route')).casefold()
    action = _clean(data.get('action')).casefold() or 'none'
    rewritten = _clean(data.get('standalone_request'), 1200) or current
    response = _clean(data.get('response'), 2400)
    confidence = data.get('confidence', 0.0)
    target = data.get('target') if isinstance(data.get('target'), dict) else {}
    entity = _clean(target.get('entity')).casefold() or 'unknown'
    scope = _clean(target.get('scope')).casefold() or 'unknown'
    reference = _clean(target.get('reference'), 500)
    ids = _clean_ids(target.get('ids'))
    filters = target.get('filters') if isinstance(target.get('filters'), dict) else {}

    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except Exception:
        confidence = 0.0

    if mode not in _ALLOWED_MODES or route not in _ALLOWED_ROUTES or action not in _ALLOWED_ACTIONS:
        return None
    if scope not in _ALLOWED_SCOPES:
        scope = 'unknown'
    if entity not in _ALLOWED_ENTITIES:
        entity = 'unknown'

    mutating = action in {'create', 'update', 'remove', 'pause', 'resume', 'run', 'execute', 'complete', 'reschedule'}
    if mutating and mode not in {'action', 'followup'}:
        return None

    return {
        'mode': mode,
        'route': route,
        'action': action,
        'standalone_request': rewritten,
        'response': response,
        'confidence': confidence,
        'references_previous_turn': bool(data.get('references_previous_turn')),
        'reason': _clean(data.get('reason'), 240),
        'target': {
            'entity': entity,
            'scope': scope,
            'reference': reference,
            'ids': ids,
            'filters': filters,
        },
    }


def _entity_catalog() -> str:
    payload: dict[str, Any] = {'schedules': [], 'tasks': []}
    try:
        for item in list_schedules(status='active', limit=24):
            payload['schedules'].append({
                'id': item.get('id'),
                'kind': item.get('kind'),
                'title': _clean(item.get('title') or item.get('message'), 100),
                'next': item.get('next_run_at'),
            })
    except Exception:
        pass
    try:
        for item in list_tasks(status='todo')[:24]:
            payload['tasks'].append({
                'id': item.get('id'),
                'title': _clean(item.get('title'), 100),
                'priority': item.get('priority'),
                'due': item.get('due'),
            })
    except Exception:
        pass
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


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
    recent = str(recent_context or '')[-3000:]
    try:
        refresh_agent_state(current_context=current)
        state = operational_state(max_actions=4)
    except Exception:
        state = ''

    now = datetime.now(tz(DEFAULT_TZ)).isoformat()
    catalog = _entity_catalog()
    system = (
        'Você é o núcleo semântico do Hermes. Interprete a mensagem pelo significado, contexto e estado atual. '
        'Retorne somente JSON válido e compacto. Perguntas nunca viram mutações. Use IDs do catálogo somente quando houver correspondência confiável. '
        'Se faltar informação indispensável para agir com segurança, use route=chat, action=answer e response com uma pergunta curta. '
        'Conversa comum usa route=chat, action=answer. Filtros temporais ficam em target.filters com period, date, hour e minute quando aplicável. '
        'Schema: '
        '{"mode":"chat|query|action|followup",'
        '"route":"time|task|automation|finance|research|developer|devops|memory|mission|connected|assistant|chat",'
        '"action":"none|create|list|status|update|remove|pause|resume|run|answer|search|execute|continue|complete|reschedule",'
        '"standalone_request":"pedido autossuficiente",'
        '"response":"resposta curta quando route=chat/action=answer",'
        '"references_previous_turn":true|false,'
        '"target":{"entity":"day|routine|reminder|alert|event|commitment|schedule|task|automation|unknown",'
        '"scope":"single|selection|all|filtered|unknown",'
        '"reference":"descrição","ids":[],"filters":{}},'
        '"confidence":0.0,"reason":"curto"}'
    )
    prompt = (
        f'AGORA:{now}\n'
        + (f'ESTADO:{state}\n' if state else '')
        + f'ENTIDADES:{catalog}\n'
        + f'CONVERSA:{recent or "(vazia)"}\n'
        + f'MENSAGEM:{current}'
    )

    parsed = _call_once(llm, prompt, system, 220)
    return _validate(parsed, current) if parsed else None
