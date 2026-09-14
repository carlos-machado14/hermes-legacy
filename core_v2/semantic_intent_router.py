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
    # Aceita texto extra do modelo pequeno, mas extrai somente o primeiro objeto JSON.
    start = text.find('{')
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(text[start:i + 1])
                    return data if isinstance(data, dict) else None
                except Exception:
                    return None
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


def _classifier_system() -> str:
    # Few-shot curto porque o modelo local é pequeno. Os exemplos ensinam a
    # distinção de intenção; não são uma lista de frases obrigatórias.
    return (
        'Você é o ROTEADOR do Hermes. Não converse com o usuário. '
        'Entenda o significado da mensagem junto do contexto e escolha a capacidade correta. '
        'Retorne SOMENTE um JSON válido, sem markdown nem explicações.\n\n'
        'Rotas: cron, finance, research, developer, devops, memory, mission, connected, assistant, chat.\n'
        'Ações cron: create, status, list, update_brief, pause, resume, run, remove, unknown.\n\n'
        'Regras semânticas:\n'
        '- cron/update_brief = quer mudar qualidade, formato, profundidade, links ou conteúdo das entregas automáticas/briefings.\n'
        '- cron/status = quer saber se uma rotina rodou, falhou ou qual seu estado.\n'
        '- cron/create = quer uma nova execução recorrente/agendada.\n'
        '- research = quer buscar/descobrir informação externa atual.\n'
        '- finance = quer consultar/alterar finanças pessoais estruturadas.\n'
        '- developer = quer trabalhar em código/repos/projeto.\n'
        '- devops = quer inspecionar/operar VPS, processos, serviços, containers ou infraestrutura.\n'
        '- memory = quer lembrar, salvar, recuperar ou corrigir memória/contexto pessoal.\n'
        '- mission = quer uma tarefa longa/durável com progresso.\n'
        '- chat = conversa/pergunta que não exige uma ferramenta especializada.\n\n'
        'Exemplos de significado:\n'
        'Mensagem: "as coisas que recebo automaticamente estão rasas; quero entender tudo sem sair do Telegram"\n'
        'Saída: {"route":"cron","action":"update_brief","confidence":0.96,"target":null,"params":{"detail_level":"detailed","summary_without_link":true,"include_links":true},"reason":"quer aprofundar entregas automáticas"}\n'
        'Mensagem: "a rotina da manhã rodou hoje?"\n'
        'Saída: {"route":"cron","action":"status","confidence":0.98,"target":null,"params":{},"reason":"consulta execução"}\n'
        'Mensagem: "todo dia às 8 me traga uma empresa sem site e com whatsapp"\n'
        'Saída: {"route":"cron","action":"create","confidence":0.98,"target":null,"params":{},"reason":"nova tarefa recorrente"}\n'
        'Mensagem: "quanto estou gastando por mês?"\n'
        'Saída: {"route":"finance","action":"summary","confidence":0.98,"target":null,"params":{},"reason":"consulta financeira"}\n\n'
        'Para cron/update_brief, params pode ter detail_level=short|normal|detailed, include_links boolean, summary_without_link boolean. '
        'Se houver ambiguidade real, reduza confidence. Não invente ação. '
        'Formato final exato: {"route":"...","action":"...","confidence":0.0,"target":null,"params":{},"reason":"..."}'
    )


def _call_classifier(llm: Callable[..., str], prompt: str, *, max_tokens: int = 150) -> dict[str, Any] | None:
    try:
        raw = llm(prompt, system=_classifier_system(), max_tokens=max_tokens)
    except Exception:
        return None
    parsed = _extract_json(raw)
    return _normalize(parsed) if parsed else None


def _repair_classification(
    text: str,
    recent: str,
    llm: Callable[..., str],
    first: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Segunda tentativa curta para modelos locais pequenos.

    O objetivo não é responder; é forçar uma escolha entre capacidades. Isso
    evita que uma classificação perdida caia direto no chat genérico.
    """
    first_text = json.dumps(first, ensure_ascii=False) if first else '(sem JSON válido)'
    prompt = (
        f'Contexto recente:\n{recent[-1000:] or "(vazio)"}\n\n'
        f'Mensagem atual:\n{text}\n\n'
        f'Primeira classificação:\n{first_text}\n\n'
        'Reavalie a INTENÇÃO. Se a pessoa estiver pedindo uma alteração em algo que recebe automaticamente, '
        'isso é cron/update_brief; se estiver perguntando se rodou, cron/status. '
        'Responda apenas com o JSON final.'
    )
    return _call_classifier(llm, prompt, max_tokens=130)


def classify(
    text: str,
    recent_context: str,
    llm: Callable[..., str],
) -> dict[str, Any] | None:
    """Classifica por intenção usando contexto, com retry para modelo local pequeno."""
    current = str(text or '').strip()
    if not current:
        return None
    recent = str(recent_context or '')[-1800:]
    prompt = (
        f'CONTEXTO RECENTE:\n{recent or "(vazio)"}\n\n'
        f'MENSAGEM ATUAL:\n{current}\n\n'
        'Escolha a capacidade pela intenção da pessoa, não por palavras isoladas. Retorne somente JSON.'
    )
    first = _call_classifier(llm, prompt)

    # Classificações úteis e confiantes passam direto.
    if first and first.get('route') != 'chat' and float(first.get('confidence') or 0.0) >= 0.72:
        return first

    # Chat com baixa/média confiança é justamente onde um modelo pequeno tende a
    # perder pedidos indiretos. Fazemos uma segunda avaliação antes do fallback.
    repaired = _repair_classification(current, recent, llm, first)
    if repaired and float(repaired.get('confidence') or 0.0) >= float((first or {}).get('confidence') or 0.0):
        return repaired
    return first
