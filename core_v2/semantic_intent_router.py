#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from typing import Any, Callable

LABELS: dict[str, tuple[str, str]] = {
    'CRON_CREATE': ('cron', 'create'),
    'CRON_STATUS': ('cron', 'status'),
    'CRON_LIST': ('cron', 'list'),
    'CRON_UPDATE_BRIEF': ('cron', 'update_brief'),
    'CRON_PAUSE': ('cron', 'pause'),
    'CRON_RESUME': ('cron', 'resume'),
    'CRON_RUN': ('cron', 'run'),
    'CRON_REMOVE': ('cron', 'remove'),
    'FINANCE': ('finance', 'unknown'),
    'RESEARCH': ('research', 'unknown'),
    'DEVELOPER': ('developer', 'unknown'),
    'DEVOPS': ('devops', 'unknown'),
    'MEMORY': ('memory', 'unknown'),
    'MISSION': ('mission', 'unknown'),
    'CONNECTED': ('connected', 'unknown'),
    'ASSISTANT': ('assistant', 'unknown'),
    'CHAT': ('chat', 'unknown'),
}


def _label_from_raw(raw: str) -> str | None:
    text = str(raw or '').upper()
    for label in LABELS:
        if re.search(rf'\b{re.escape(label)}\b', text):
            return label
    return None


def _classify_label(text: str, recent: str, llm: Callable[..., str]) -> str | None:
    system = (
        'Você é somente o classificador de intenção do Hermes. NÃO responda ao usuário. '
        'Escolha EXATAMENTE UMA etiqueta e escreva somente a etiqueta, sem explicação.\n\n'
        'Etiquetas permitidas:\n'
        'CRON_CREATE = criar nova rotina/tarefa agendada ou recorrente\n'
        'CRON_STATUS = diagnosticar se uma rotina executou, falhou ou seu estado\n'
        'CRON_LIST = listar rotinas\n'
        'CRON_UPDATE_BRIEF = mudar qualidade, profundidade, formato, links ou conteúdo das entregas automáticas/briefings que o usuário recebe\n'
        'CRON_PAUSE = pausar rotina\n'
        'CRON_RESUME = retomar rotina\n'
        'CRON_RUN = executar rotina agora\n'
        'CRON_REMOVE = remover rotina\n'
        'FINANCE = consultar ou alterar finanças pessoais\n'
        'RESEARCH = pesquisar informação externa atual\n'
        'DEVELOPER = código, repo, projeto, implementação, bug\n'
        'DEVOPS = VPS, processo, serviço, container, infraestrutura\n'
        'MEMORY = memória/contexto pessoal\n'
        'MISSION = tarefa longa/durável\n'
        'CONNECTED = agenda/email/github/whatsapp via integração\n'
        'ASSISTANT = ação geral do assistente que não cai acima\n'
        'CHAT = conversa comum sem ação especializada\n\n'
        'Importante: quando o usuário reclama que algo que recebe automaticamente está raso, superficial, curto, sem contexto, '
        'ou quer entender melhor sem abrir links/sair do Telegram, isso é CRON_UPDATE_BRIEF. '
        'Quando ele pergunta se uma rotina rodou, isso é CRON_STATUS. '
        'Quando quer uma nova rotina, CRON_CREATE.'
    )
    prompt = (
        f'CONTEXTO RECENTE:\n{recent[-1200:] or "(vazio)"}\n\n'
        f'MENSAGEM ATUAL:\n{text}\n\n'
        'ETIQUETA:'
    )
    try:
        raw = llm(prompt, system=system, max_tokens=24)
    except Exception:
        return None
    return _label_from_raw(raw)


def _extract_brief_params(text: str, recent: str, llm: Callable[..., str]) -> dict[str, Any]:
    system = (
        'Extraia preferências de briefing. Retorne SOMENTE JSON válido e curto. '
        'Campos possíveis: detail_level (short|normal|detailed), include_links (boolean), summary_without_link (boolean). '
        'Não invente campos. Se o usuário quer mais contexto, mais profundidade ou diz que está superficial, detail_level=detailed. '
        'Se quer entender sem abrir link/sair do Telegram, summary_without_link=true. '
        'Se quer manter links apenas como fonte, include_links=true.'
    )
    prompt = (
        f'CONTEXTO:\n{recent[-800:] or "(vazio)"}\n\n'
        f'MENSAGEM:\n{text}\n\nJSON:'
    )
    try:
        raw = llm(prompt, system=system, max_tokens=90)
    except Exception:
        return {}
    raw = str(raw or '').strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        m = re.search(r'\{.*?\}', raw, re.DOTALL)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def classify(text: str, recent_context: str, llm: Callable[..., str]) -> dict[str, Any] | None:
    current = str(text or '').strip()
    if not current:
        return None
    recent = str(recent_context or '')[-1800:]

    # Modelo pequeno se sai muito melhor escolhendo uma etiqueta curta do que
    # gerando JSON completo + confidence + params em uma única chamada.
    label = _classify_label(current, recent, llm)
    if not label:
        return None

    route, action = LABELS[label]
    params: dict[str, Any] = {}
    confidence = 0.93 if label != 'CHAT' else 0.65

    if label == 'CRON_UPDATE_BRIEF':
        params = _extract_brief_params(current, recent, llm)
        # Defaults seguros quando o extrator pequeno falha: a intenção já foi
        # classificada como aprofundar/alterar briefing, então tornamos a entrega
        # mais autoexplicativa sem mexer em horários nem remover links.
        if not params:
            params = {
                'detail_level': 'detailed',
                'summary_without_link': True,
                'include_links': True,
            }

    return {
        'route': route,
        'action': action,
        'confidence': confidence,
        'target': None,
        'params': params,
        'reason': f'classificado como {label}',
    }
