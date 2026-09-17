#!/usr/bin/env python3
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable

from temporal_query import resolve_temporal_range
from time_store import DEFAULT_TZ, tz

_ACTIONS = {
    'L': 'list', 'C': 'create', 'R': 'remove', 'U': 'update', 'P': 'pause',
    'V': 'resume', 'X': 'run', 'D': 'complete', 'G': 'reschedule', 'N': 'answer',
    'H': 'search', 'S': 'status',
}
_ENTITIES = {
    'A': 'day', 'M': 'reminder', 'L': 'alert', 'E': 'event', 'C': 'commitment',
    'R': 'routine', 'T': 'task', 'S': 'schedule', 'O': 'unknown',
}
_SCOPES = {'1': 'single', 'A': 'all', 'F': 'filtered', 'P': 'selection', 'U': 'unknown'}
_MODES = {'Q': 'query', 'A': 'action', 'F': 'followup', 'C': 'chat'}
_ROUTES = {
    'T': 'time', 'K': 'task', 'U': 'automation', 'S': 'assistant', 'W': 'research',
    'D': 'developer', 'O': 'devops', 'M': 'memory', 'F': 'finance', 'C': 'chat',
}
_MUTATING = {'create', 'update', 'remove', 'pause', 'resume', 'run', 'complete', 'reschedule'}


def _parse_label(raw: str) -> tuple[str, str, str, str, str] | None:
    text = str(raw or '').upper().strip()
    match = re.search(r'([LCRUPVXDGHNS])\s*\|\s*([AMLECRTSO])\s*\|\s*([1AFPU])\s*\|\s*([QAFC])\s*\|\s*([TKUSWDOMFC])', text)
    if not match:
        return None
    return tuple(match.groups())  # type: ignore[return-value]


def _temporal_filters(text: str) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    period = resolve_temporal_range(text)
    if period is not None:
        today = datetime.now(tz(DEFAULT_TZ)).date()
        if period.start == period.end:
            filters['date'] = period.start.isoformat()
            if period.start == today:
                filters['period'] = 'today'
            elif period.start == today.fromordinal(today.toordinal() + 1):
                filters['period'] = 'tomorrow'
        else:
            label = period.label.casefold()
            if 'semana que vem' in label:
                filters['period'] = 'next_week'
            elif 'esta semana' in label:
                filters['period'] = 'this_week'
            elif 'mês que vem' in label:
                filters['period'] = 'next_month'
            elif 'este mês' in label:
                filters['period'] = 'this_month'
            filters['date_start'] = period.start.isoformat()
            filters['date_end'] = period.end.isoformat()

    # Extração objetiva de horário; não participa da decisão de intenção.
    hour_match = re.search(r'(?<!\d)([01]?\d|2[0-3])(?:[:h](\d{2}))?\s*h?\b', text.casefold())
    if hour_match:
        filters['hour'] = int(hour_match.group(1))
        filters['minute'] = int(hour_match.group(2) or 0)
    return filters


def _reference(text: str, entity: str, action: str, scope: str) -> str:
    # O classificador decide intenção/entidade. Aqui só preservamos texto útil para
    # criação ou busca filtrada; o executor e os parsers locais fazem o restante.
    current = re.sub(r'\s+', ' ', str(text or '')).strip()
    if not current:
        return ''
    if action == 'create' or entity == 'task':
        return current[:360]
    if scope in {'filtered', 'single'} and entity not in {'day', 'schedule'}:
        return current[:360]
    return ''


def decide(text: str, recent_context: str, classifier: Callable[[str, str], str]) -> dict[str, Any] | None:
    current = str(text or '').strip()
    if not current:
        return None

    try:
        raw = classifier(current, recent_context)
    except Exception:
        return None

    parsed = _parse_label(raw)
    if not parsed:
        return None

    action_code, entity_code, scope_code, mode_code, route_code = parsed
    action = _ACTIONS[action_code]
    entity = _ENTITIES[entity_code]
    scope = _SCOPES[scope_code]
    mode = _MODES[mode_code]
    route = _ROUTES[route_code]

    # Rotinas comuns são schedules locais; isso permite que create/list/remove/
    # pause/resume usem o executor estruturado em vez do roteador legado.
    if entity == 'routine' and action in {'create', 'list', 'status', 'remove', 'pause', 'resume', 'reschedule'}:
        route = 'time'

    if action in _MUTATING and mode not in {'action', 'followup'}:
        return None

    # Escopo desconhecido em mutação é deliberadamente bloqueado.
    if action in _MUTATING and scope == 'unknown':
        return {
            'mode': 'chat',
            'route': 'chat',
            'action': 'answer',
            'standalone_request': current,
            'response': 'Preciso saber exatamente qual item você quer alterar.',
            'confidence': 0.95,
            'references_previous_turn': mode == 'followup',
            'reason': 'ambiguous_mutation_scope',
            'target': {'entity': entity, 'scope': scope, 'reference': '', 'ids': [], 'filters': {}},
        }

    filters = _temporal_filters(current)
    reference = _reference(current, entity, action, scope)

    return {
        'mode': mode,
        'route': route,
        'action': action,
        'standalone_request': current,
        'response': '',
        'confidence': 0.92,
        'references_previous_turn': mode == 'followup',
        'reason': 'compact_local_classifier',
        'target': {
            'entity': entity,
            'scope': scope,
            'reference': reference,
            'ids': [],
            'filters': filters,
        },
    }
