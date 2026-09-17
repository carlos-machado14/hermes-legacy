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
    for item in value[:80]:
        ref = _clean(item, 64)
        if re.fullmatch(r'[0-9a-fA-F]{6,32}', ref) and ref not in out:
            out.append(ref)
    return out


def _validate(data: dict[str, Any], current: str) -> dict[str, Any] | None:
    mode = _clean(data.get('mode')).casefold()
    route = _clean(data.get('route')).casefold()
    action = _clean(data.get('action')).casefold() or 'none'
    rewritten = _clean(data.get('standalone_request'), 2200) or current
    response = _clean(data.get('response'), 5000)
    confidence = data.get('confidence', 0.0)
    target = data.get('target') if isinstance(data.get('target'), dict) else {}
    entity = _clean(target.get('entity')).casefold() or 'unknown'
    scope = _clean(target.get('scope')).casefold() or 'unknown'
    reference = _clean(target.get('reference'), 800)
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
        'reason': _clean(data.get('reason'), 300),
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
        for item in list_schedules(status='active', limit=60):
            payload['schedules'].append({
                'id': item.get('id'),
                'kind': item.get('kind'),
                'title': item.get('title'),
                'message': item.get('message'),
                'next_run_at': item.get('next_run_at'),
                'timezone': item.get('timezone'),
                'recurrence': item.get('recurrence'),
            })
    except Exception:
        pass
    try:
        for item in list_tasks(status='todo')[:60]:
            payload['tasks'].append({
                'id': item.get('id'),
                'title': item.get('title'),
                'priority': item.get('priority'),
                'due': item.get('due'),
                'kind': item.get('kind'),
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
    recent = str(recent_context or '')[-6000:]
    try:
        refresh_agent_state(current_context=current)
        state = operational_state(max_actions=6)
    except Exception:
        state = ''

    now = datetime.now(tz(DEFAULT_TZ)).isoformat()
    catalog = _entity_catalog()
    system = (
        'Você é o núcleo semântico do Hermes. Interprete linguagem natural pelo significado, contexto e estado atual, sem palavras-chave, frases especiais ou exemplos de comandos. '
        'Retorne somente JSON válido. Uma pergunta nunca deve virar mutação. Quando uma ação depende de um item já conhecido, use os IDs do catálogo quando houver correspondência confiável. '
        'Se houver ambiguidade que impeça agir com segurança, retorne route=chat, action=answer e use response para pedir apenas a informação indispensável. '
        'Para conversa comum, retorne route=chat, action=answer e escreva a resposta em response. '
        'Filtros temporais devem ser estruturados em target.filters usando period, date, hour e minute quando aplicável. '
        'Schema: '
        '{"mode":"chat|query|action|followup",'
        '"route":"time|task|automation|finance|research|developer|devops|memory|mission|connected|assistant|chat",'
        '"action":"none|create|list|status|update|remove|pause|resume|run|answer|search|execute|continue|complete|reschedule",'
        '"standalone_request":"pedido autossuficiente",'
        '"response":"resposta apenas quando route=chat/action=answer",'
        '"references_previous_turn":true|false,'
        '"target":{"entity":"day|routine|reminder|alert|event|commitment|schedule|task|automation|unknown",'
        '"scope":"single|selection|all|filtered|unknown",'
        '"reference":"descrição sem inventar dados",'
        '"ids":[],"filters":{}},'
        '"confidence":0.0,"reason":"curto"}'
    )
    prompt = (
        f'DATA_HORA_ATUAL:{now}\n'
        + (f'ESTADO_OPERACIONAL:\n{state}\n' if state else '')
        + f'CATALOGO_DE_ENTIDADES:\n{catalog}\n'
        + f'CONVERSA_RECENTE:\n{recent or "(vazia)"}\n'
        + f'MENSAGEM_ATUAL:\n{current}'
    )

    parsed = _call_once(llm, prompt, system, 520)
    if parsed is None:
        parsed = _call_once(llm, prompt, system, 260)
    return _validate(parsed, current) if parsed else None
