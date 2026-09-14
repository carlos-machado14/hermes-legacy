#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from typing import Any, Callable

ALLOWED_ROUTES = {
    'cron', 'finance', 'research', 'developer', 'devops', 'memory',
    'mission', 'connected', 'assistant', 'chat',
}
CRON_ACTIONS = {
    'create', 'status', 'list', 'update_brief', 'pause', 'resume',
    'run', 'remove', 'unknown',
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


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    route = str(data.get('route') or 'chat').strip().lower()
    if route not in ALLOWED_ROUTES:
        route = 'chat'
    action = str(data.get('action') or 'unknown').strip().lower()
    if route == 'cron' and action not in CRON_ACTIONS:
        action = 'unknown'
    try:
        confidence = float(data.get('confidence', 0.0))
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    params = data.get('params') if isinstance(data.get('params'), dict) else {}
    target = str(data.get('target') or '').strip() or None
    return {
        'route': route,
        'action': action,
        'confidence': confidence,
        'target': target,
        'params': params,
        'reason': str(data.get('reason') or '')[:240],
    }


def classify(
    text: str,
    recent_context: str,
    llm: Callable[..., str],
) -> dict[str, Any] | None:
    """Classifica intenção por significado, não por lista de frases.

    A saída é pequena e estruturada. Se o classificador falhar, o Core segue pelos
    roteadores legados, portanto a camada semântica é progressiva e fail-open.
    """
    current = str(text or '').strip()
    if not current:
        return None
    recent = str(recent_context or '')[-1800:]
    system = (
        'Você é o roteador semântico do Hermes. Sua única tarefa é entender a intenção real '
        'da mensagem considerando o contexto recente. Não responda ao usuário. Retorne SOMENTE '
        'um objeto JSON válido, sem markdown. Rotas permitidas: cron, finance, research, developer, '
        'devops, memory, mission, connected, assistant, chat. '
        'Para route=cron, action deve ser uma de: create, status, list, update_brief, pause, resume, run, remove, unknown. '
        'Use cron/update_brief quando o usuário quer mudar formato, detalhamento, links, conteúdo ou estilo dos briefings/rotinas, '
        'mesmo sem usar verbos exatos como atualizar/melhorar. Use cron/status somente quando ele quer diagnosticar execução. '
        'Use cron/create quando quer uma nova rotina agendada. '
        'Em params, para update_brief, extraia quando possível: detail_level=short|normal|detailed, '
        'include_links=true|false, summary_without_link=true|false. '
        'Em target, coloque o nome/ID do job quando aplicável. '
        'Formato: {"route":"...","action":"...","confidence":0.0,"target":null,"params":{},"reason":"curto"}.'
    )
    prompt = (
        f'CONTEXTO RECENTE:\n{recent or "(vazio)"}\n\n'
        f'MENSAGEM ATUAL:\n{current}\n\n'
        'Classifique pela intenção, não por palavras isoladas.'
    )
    try:
        raw = llm(prompt, system=system, max_tokens=180)
    except Exception:
        return None
    parsed = _extract_json(raw)
    return _normalize(parsed) if parsed else None
