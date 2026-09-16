#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from typing import Any, Callable

_ALLOWED_MODES = {'chat', 'query', 'action', 'followup'}
_ALLOWED_ROUTES = {
    'time', 'finance', 'research', 'developer', 'devops', 'memory',
    'mission', 'connected', 'assistant', 'chat',
}
_ALLOWED_ACTIONS = {
    'none', 'create', 'list', 'status', 'update', 'remove', 'pause',
    'resume', 'run', 'answer', 'search', 'execute', 'continue',
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


def _validate(data: dict[str, Any], current: str) -> dict[str, Any] | None:
    mode = _clean(data.get('mode')).casefold()
    route = _clean(data.get('route')).casefold()
    action = _clean(data.get('action')).casefold() or 'none'
    rewritten = _clean(data.get('standalone_request'), 1800) or current
    confidence = data.get('confidence', 0.0)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except Exception:
        confidence = 0.0

    if mode not in _ALLOWED_MODES or route not in _ALLOWED_ROUTES or action not in _ALLOWED_ACTIONS:
        return None

    # Ação mutável precisa ter sido classificada explicitamente como action/followup.
    mutating = action in {'create', 'update', 'remove', 'pause', 'resume', 'run', 'execute'}
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
    }


def decide(text: str, recent_context: str, llm: Callable[..., str]) -> dict[str, Any] | None:
    current = str(text or '').strip()
    if not current:
        return None
    recent = str(recent_context or '')[-4500:]

    system = (
        'Você é o cérebro de roteamento conversacional do Hermes. Não responda ao usuário. '
        'Entenda a intenção usando a mensagem atual e a conversa recente. A mensagem atual sempre tem prioridade. '
        'Sua função é transformar follow-ups em pedidos autossuficientes e escolher a ferramenta/domínio correto. '
        'Retorne SOMENTE JSON válido, sem markdown.\n\n'
        'Schema exato:\n'
        '{"mode":"chat|query|action|followup","route":"time|finance|research|developer|devops|memory|mission|connected|assistant|chat",'
        '"action":"none|create|list|status|update|remove|pause|resume|run|answer|search|execute|continue",'
        '"standalone_request":"pedido completo em português, preservando a intenção do usuário",'
        '"references_previous_turn":true|false,"confidence":0.0,"reason":"curto"}\n\n'
        'Regras críticas:\n'
        '1. Nunca transforme pergunta em ação. "Tenho dois alertas às 8:30?" é query/time/list, não create.\n'
        '2. Datas e horários não significam criação por si só.\n'
        '3. "e amanhã?" após falar da agenda é followup/time/list e deve virar algo como "mostrar minha agenda de amanhã".\n'
        '4. "cancela o da água" após falar de lembretes é followup/time/remove e o standalone_request deve manter o assunto água.\n'
        '5. "me avisa amanhã..." é action/time/create.\n'
        '6. Conversa comum é chat/chat/none.\n'
        '7. Não invente IDs, horários, pessoas ou detalhes que não estejam na mensagem ou no contexto.\n'
        '8. Se houver ambiguidade real, preserve-a no standalone_request; a ferramenta pode pedir esclarecimento.\n'
        '9. Para código/repos use developer; VPS/processos use devops; pesquisas atuais use research.\n'
        '10. O parser de datas é apenas uma ferramenta posterior. Você decide intenção e contexto primeiro.'
    )
    prompt = (
        'CONVERSA RECENTE:\n' + (recent or '(sem histórico)') +
        '\n\nMENSAGEM ATUAL:\n' + current +
        '\n\nJSON:'
    )
    try:
        raw = llm(prompt, system=system, max_tokens=220)
    except Exception:
        return None
    parsed = _extract_json(raw)
    return _validate(parsed, current) if parsed else None
