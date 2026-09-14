#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

from capability_registry import list_capabilities
from conversation_memory import compact as recent_conversation

ROOT = Path.home() / '.hermes' / 'core-v2'
LOG = ROOT / 'logs' / 'semantic_agent.jsonl'

_ALLOWED_INTENTS = {
    'chat', 'research', 'current_info', 'cron_create', 'cron_query', 'cron_modify',
    'system_action', 'developer_action', 'mission', 'memory', 'assistant_action',
}


def _log(event: str, payload: dict[str, Any]) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        row = {'ts': int(time.time()), 'event': event, **payload}
        with LOG.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    except Exception:
        pass


def _chat_key() -> str:
    return (os.getenv('HERMES_CHAT_KEY') or 'default').strip() or 'default'


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


def _capability_summary() -> str:
    rows = list_capabilities()
    lines = []
    for row in rows:
        lines.append(
            f"- {row.get('name')}: {row.get('description')} "
            f"(risco={row.get('risk')}, aprovação={bool(row.get('requires_approval'))}, execução={row.get('execution')})"
        )
    return '\n'.join(lines)


def interpret(text: str, llm: Callable[..., str]) -> dict[str, Any] | None:
    current = str(text or '').strip()
    if not current:
        return None
    try:
        recent = recent_conversation(limit=6, max_chars=1800)
    except Exception:
        recent = ''

    system = '''Você é o cérebro de roteamento de um agente pessoal autônomo chamado Hermes/Gepeto.
Sua função NÃO é responder ao usuário. Sua função é compreender semanticamente o objetivo atual, considerando a conversa recente apenas quando houver referência real ao assunto anterior.
Não use palavras isoladas como regra. Entenda a intenção completa.

Retorne SOMENTE JSON válido com estes campos:
intent: um de chat|research|current_info|cron_create|cron_query|cron_modify|system_action|developer_action|mission|memory|assistant_action
confidence: número 0..1
goal: objetivo do usuário em uma frase
needs_tools: boolean
capabilities: lista de nomes de capacidades úteis
requires_confirmation: boolean
missing: lista de informações realmente necessárias antes de executar
reason: explicação curta da classificação

Regras:
- chat = conversa/pergunta conceitual que não precisa executar ferramenta.
- research = pesquisar/coletar/comparar dados externos agora; NÃO é rotina só porque menciona empresa, dados ou "mande".
- current_info = fatos que precisam estar atualizados (clima, temperatura, notícias, cotação, status atual etc.).
- cron_create = somente quando o usuário quer criar/agendar recorrência/lembrete/automação futura.
- cron_query = listar, verificar existência/status/execução de rotinas.
- cron_modify = editar, pausar, retomar, remover ou executar uma rotina existente.
- system_action = ação no host/serviço/infra.
- developer_action = código, GitHub, deploy, arquivos de projeto.
- mission = trabalho explicitamente longo/multi-etapas que deve continuar até terminar.
- memory = lembrar/consultar memória pessoal.
- assistant_action = ação geral não coberta acima.
- Leituras/pesquisas não precisam de confirmação.
- Qualquer mutação externa deve exigir confirmação, exceto se já estiver em um fluxo pendente que explicitamente pediu confirmação.
- Se faltar dado essencial, preencha missing; não invente.
- A mensagem atual tem prioridade. Contexto antigo jamais deve transformar uma pergunta nova em cron.
'''
    prompt = (
        'CAPACIDADES DISPONÍVEIS:\n' + _capability_summary() +
        '\n\nCONVERSA RECENTE:\n' + (recent or '(vazia)') +
        '\n\nMENSAGEM ATUAL:\n' + current + '\n\nJSON:'
    )
    try:
        raw = llm(prompt, system=system, max_tokens=240)
    except Exception as exc:
        _log('interpret_error', {'chat': _chat_key(), 'error': str(exc)[:300], 'text': current[:400]})
        return None
    data = _extract_json(raw)
    if not data:
        return None
    intent = str(data.get('intent') or '').strip()
    if intent not in _ALLOWED_INTENTS:
        return None
    try:
        confidence = float(data.get('confidence') or 0.0)
    except Exception:
        confidence = 0.0
    data['confidence'] = confidence
    data['missing'] = [str(x) for x in (data.get('missing') or []) if str(x).strip()][:6]
    data['capabilities'] = [str(x) for x in (data.get('capabilities') or []) if str(x).strip()][:8]
    _log('interpreted', {'chat': _chat_key(), 'text': current[:500], 'intent': data})
    return data


def _research(text: str, current: bool = False) -> str:
    from web_research import format_research, research, research_company
    low = text.casefold()
    companyish = any(k in low for k in ('empresa', 'empresas', 'lead', 'leads', 'negócio', 'negocio', 'sem site'))
    try:
        # Company research is intentionally capped. The old route crawled too many
        # candidates and frequently exceeded the Telegram fastpath SLA.
        report = research_company(text, limit=2) if companyish else research(text, limit=6)
        rendered = format_research(report)
        if not rendered.strip():
            return 'Não encontrei dados públicos suficientes para responder com confiança.'
        return rendered
    except Exception as exc:
        return f'Não consegui concluir a pesquisa com fonte real agora. Detalhe: {exc}'


def _cron(text: str) -> str:
    from cron_manager import handle
    try:
        return handle(text, chat_key=_chat_key())
    except TypeError:
        return handle(text)


def _system_action(text: str, llm: Callable[..., str]) -> str | None:
    from action_orchestrator import handle
    return handle(text, llm=llm)


def _developer(text: str) -> str | None:
    try:
        from developer_router import handle
        return handle(text)
    except Exception:
        return None


def _memory(text: str) -> str | None:
    try:
        from memory_router import handle
        return handle(text)
    except Exception:
        return None


def _mission(text: str) -> str | None:
    try:
        from mission_router import handle
        return handle(text)
    except Exception:
        return None


def _missing_reply(intent: dict[str, Any]) -> str:
    missing = intent.get('missing') or []
    goal = str(intent.get('goal') or 'essa ação')
    if len(missing) == 1:
        return f'Entendi que você quer {goal}. Antes de continuar, preciso saber: {missing[0]}.'
    return 'Entendi o objetivo. Antes de continuar, preciso destas informações: ' + '; '.join(missing) + '.'


def handle(text: str, llm: Callable[..., str]) -> str | None:
    current = str(text or '').strip()
    if not current:
        return None

    # Pending action/confirmation has priority over fresh interpretation. This keeps
    # short replies such as "sim", "não" and corrections bound to the right plan.
    try:
        from action_orchestrator import action_status, handle as handle_action
        status = action_status()
        if status.startswith('Há uma ação aguardando confirmação:'):
            result = handle_action(current, llm=llm)
            if result is not None:
                return result
    except Exception:
        pass

    # Pending cron drafts are handled by cron_manager itself. Avoid asking the LLM
    # to reinterpret a short frequency/confirmation reply out of context.
    try:
        from cron_manager import _pending_get as cron_pending_get
        if cron_pending_get(_chat_key()) is not None:
            return _cron(current)
    except Exception:
        pass

    intent = interpret(current, llm)
    if not intent or float(intent.get('confidence') or 0.0) < 0.62:
        return None

    kind = str(intent.get('intent'))
    if kind == 'chat':
        return None
    if intent.get('missing'):
        return _missing_reply(intent)
    if kind in {'research', 'current_info'}:
        return _research(current, current=(kind == 'current_info'))
    if kind in {'cron_create', 'cron_query', 'cron_modify'}:
        return _cron(current)
    if kind == 'system_action':
        return _system_action(current, llm)
    if kind == 'developer_action':
        # Mutating developer actions first pass through the universal action
        # orchestrator so they cannot claim execution without confirmation.
        if bool(intent.get('requires_confirmation')):
            result = _system_action(current, llm)
            if result is not None:
                return result
        return _developer(current)
    if kind == 'mission':
        return _mission(current)
    if kind == 'memory':
        return _memory(current)
    if kind == 'assistant_action':
        try:
            from universal_router import handle as universal_handle
            return universal_handle(current)
        except Exception:
            return None
    return None
