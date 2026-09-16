#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from typing import Any, Callable

from agent_state import compact as operational_state, refresh as refresh_agent_state

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
    'routine', 'reminder', 'alert', 'event', 'commitment', 'schedule',
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
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _clean(value: Any, limit: int = 1200) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit]


def _clean_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:50]:
        ref = _clean(item, 64)
        if re.fullmatch(r'[0-9a-fA-F]{6,32}', ref) and ref not in out:
            out.append(ref)
    return out


def _validate(data: dict[str, Any], current: str) -> dict[str, Any] | None:
    mode = _clean(data.get('mode')).casefold()
    route = _clean(data.get('route')).casefold()
    action = _clean(data.get('action')).casefold() or 'none'
    rewritten = _clean(data.get('standalone_request'), 1800) or current
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


def _call_once(llm: Callable[..., str], prompt: str, system: str, max_tokens: int) -> dict[str, Any] | None:
    try:
        raw = llm(prompt, system=system, max_tokens=max_tokens)
    except Exception:
        return None
    parsed = _extract_json(raw)
    return parsed if parsed else None


def decide(text: str, recent_context: str, llm: Callable[..., str]) -> dict[str, Any] | None:
    current = str(text or '').strip()
    if not current:
        return None
    recent = str(recent_context or '')[-5000:]
    try:
        refresh_agent_state(current_context=current)
        state = operational_state(max_actions=5)
    except Exception:
        state = ''

    system = (
        'Você é o cérebro semântico de roteamento do Hermes. Não responda ao usuário. '
        'Entenda a intenção real da mensagem atual usando a conversa recente e o estado operacional persistente. '
        'Não dependa de frases exatas, palavras mágicas ou templates. '
        'A mensagem atual tem prioridade, mas pronomes, referências, elipses, objetivos e pendências devem ser resolvidos pelo contexto. '
        'Converta linguagem natural livre em uma intenção estruturada que um executor determinístico possa cumprir. '
        'Retorne SOMENTE JSON válido, sem markdown.\n\n'
        'Schema:\n'
        '{"mode":"chat|query|action|followup",'
        '"route":"time|task|automation|finance|research|developer|devops|memory|mission|connected|assistant|chat",'
        '"action":"none|create|list|status|update|remove|pause|resume|run|answer|search|execute|continue|complete|reschedule",'
        '"standalone_request":"pedido completo e autossuficiente em português",'
        '"references_previous_turn":true|false,'
        '"target":{"entity":"routine|reminder|alert|event|commitment|schedule|task|automation|unknown",'
        '"scope":"single|selection|all|filtered|unknown",'
        '"reference":"descrição curta do alvo sem inventar dados",'
        '"ids":[],"filters":{}},'
        '"confidence":0.0,"reason":"curto"}\n\n'
        'Princípios:\n'
        '1. Classifique pelo significado, não pela presença de palavras específicas. Variações, gírias, abreviações e formas indiretas devem funcionar.\n'
        '2. Nunca transforme pergunta em ação. Datas/horários sozinhos não criam nada.\n'
        '3. Use o estado operacional para entender o foco atual, tarefas abertas, agendas, objetivos e resultados recentes.\n'
        '4. Se o usuário se refere ao conjunto que o Hermes acabou de listar, use scope=selection e references_previous_turn=true.\n'
        '5. Se o usuário pede todos os itens de uma categoria, use scope=all com entity correto.\n'
        '6. Se pede apenas um item descrito por assunto, use scope=single e reference com o assunto.\n'
        '7. Não invente IDs. Preencha ids apenas quando eles aparecem literalmente na conversa, no estado ou na mensagem atual.\n'
        '8. Tarefas e agenda são entidades distintas: task é trabalho a concluir; routine/reminder/event/commitment pertencem ao domínio time.\n'
        '9. Follow-ups curtos devem ser reconstruídos semanticamente.\n'
        '10. O usuário não precisa memorizar comandos. A mesma intenção expressa de outra forma deve gerar a mesma estrutura.\n'
        '11. Quando o usuário comunica progresso, conclusão, impedimento ou mudança de plano, preserve esse contexto para o próximo passo.\n'
        '12. Se houver ambiguidade real, preserve-a; o executor pode pedir apenas o dado indispensável.'
    )
    prompt = (
        (state + '\n\n' if state else '') +
        'CONVERSA RECENTE:\n' + (recent or '(sem histórico)') +
        '\n\nMENSAGEM ATUAL:\n' + current +
        '\n\nProduza a intenção estruturada:'
    )

    parsed = _call_once(llm, prompt, system, 280)
    if parsed is None:
        compact_system = (
            'Classifique semanticamente a intenção do usuário e retorne apenas JSON no schema solicitado. '
            'Use contexto e estado operacional para resolver referências. Não invente dados.'
        )
        parsed = _call_once(llm, prompt, compact_system + '\n' + system[-2400:], 190)
    return _validate(parsed, current) if parsed else None
