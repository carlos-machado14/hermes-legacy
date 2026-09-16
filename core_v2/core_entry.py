#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import sys
import time
from typing import Callable

import hermes_core
from assistant_router import handle as handle_assistant_command
from complexity_router import classify as classify_complexity
from connected_router import handle as handle_connected_command
from context_builder import compact as compact_context
from contextual_router import handle as handle_contextual
from conversation_action_router import handle as handle_conversation_action
from conversation_brain import decide as brain_decide
from conversation_memory import add as remember_turn, compact as recent_conversation
from developer_router import handle as handle_developer_command
from domain_router import classify as classify_domain
from finance_router import handle as handle_finance_command
from memory_router import handle as handle_memory_command
from memory_vault import append_daily, retrieve as retrieve_memory, sync_state_snapshots
from mission_router import handle as handle_mission_command
from telemetry import emit, trace_id
from time_router import handle as handle_time_command
from universal_router import handle as handle_universal_command

_original_llm = hermes_core.llm

_EXACT_REPLY_RE = re.compile(
    r'^\s*(?:responda|responde)\s+(?:apenas|somente)\s*:?\s*(.+?)\s*$',
    re.IGNORECASE | re.DOTALL,
)
_PERSONAL_HINTS = (
    'meu ', 'minha ', 'meus ', 'minhas ', 'sobre mim', 'de mim', 'para mim', 'pra mim',
    'meu perfil', 'meus dados', 'minha memória', 'minha memoria', 'lembra de', 'lembre de',
    'meu objetivo', 'meus objetivos', 'minha tarefa', 'minhas tarefas', 'meu projeto', 'meus projetos',
    'minha rotina', 'minhas rotinas', 'meus gastos', 'minhas despesas', 'minhas finanças', 'minhas financas',
    'o que você sabe sobre mim', 'o que voce sabe sobre mim',
)


def _is_timeout_error(exc: Exception) -> bool:
    text = str(exc).casefold()
    return any(k in text for k in ('timed out', 'timeout', 'readtimeout', 'pooltimeout'))


def _needs_personal_context(prompt: str) -> bool:
    low = prompt.casefold()
    return any(hint in low for hint in _PERSONAL_HINTS)


def _deterministic_reply(text: str) -> str | None:
    match = _EXACT_REPLY_RE.match(text)
    if not match:
        return None
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    return value[:1200] or None


def _retry_small(prompt: str, system: str) -> str | None:
    try:
        return _original_llm(
            prompt,
            system=system + (
                '\nResponda de forma curta e conclusiva. '
                'Se faltar informação, diga exatamente qual dado falta. '
                'Não prometa trabalho em segundo plano e não invente resultados ou ferramentas.'
            ),
            max_tokens=160,
        )
    except Exception:
        return None


def _contextual_llm(prompt: str, system: str | None = None, max_tokens: int | None = None) -> str:
    """LLM de resposta sempre recebe conversa recente; memória longa continua seletiva."""
    profile = classify_complexity(prompt)
    os.environ['HERMES_COMPLEXITY'] = profile.tier
    low = prompt.casefold().strip()

    route_started = time.perf_counter()
    route = classify_domain(prompt)
    route_ms = (time.perf_counter() - route_started) * 1000

    context = ''
    long_term = ''
    context_started = time.perf_counter()
    use_personal = profile.use_personal or _needs_personal_context(prompt)
    if use_personal and profile.personal_items > 0:
        context = compact_context(max_items=max(2, profile.personal_items))
        sync_state_snapshots()
        if profile.memory_limit > 0 and profile.memory_chars > 0:
            long_term = retrieve_memory(
                prompt,
                limit=profile.memory_limit,
                max_chars=profile.memory_chars,
            )

    # Conversa curta é barata e sempre entra. Isso impede que cada prompt pareça uma nova sessão.
    recent = recent_conversation(limit=8, max_chars=3600)
    context_ms = (time.perf_counter() - context_started) * 1000

    base_system = (
        'Você é Hermes, uma inteligência artificial pessoal e geral. Responda em português do Brasil. '
        'Mantenha continuidade entre as mensagens e resolva referências usando a conversa recente. '
        'A mensagem atual tem prioridade sobre o histórico. '
        'Entenda antes de agir. Nunca transforme pergunta em ação. '
        'Ferramentas e parsers são braços auxiliares: não trate palavras-chave como intenção por si só. '
        'Use somente capacidades reais. Não invente ações executadas, resultados, integrações ou dados. '
        'Quando faltar informação indispensável, peça somente o dado que falta. '
        'Ações externas ou sensíveis exigem aprovação quando aplicável.'
    )
    if system:
        base_system += '\n' + system

    sections = [f"ROTA SUGERIDA: {route['primary_domain']} / {route['agent']}"]
    if recent:
        sections.append('CONVERSA RECENTE\n' + recent)
    if context:
        sections.append(context)
    if long_term:
        sections.append('MEMÓRIA RELEVANTE\n' + long_term)
    sections.append('MENSAGEM ATUAL\n' + prompt)
    sections.append('Responda ao pedido atual levando em conta a continuidade da conversa.')
    enriched = '\n\n'.join(sections)

    requested = max_tokens or profile.max_output_tokens
    if max_tokens is None and any(k in low for k in ('detalhadamente', 'completo', 'completa', 'passo a passo', 'aprofund')):
        requested = max(requested, 520)

    emit(
        'core.context',
        elapsed_ms=context_ms,
        tier=profile.tier,
        route=route.get('primary_domain'),
        route_ms=round(route_ms, 2),
        use_recent=bool(recent),
        use_personal=bool(context or long_term),
        prompt_chars=len(enriched),
        max_output_tokens=requested,
    )

    llm_started = time.perf_counter()
    try:
        result = _original_llm(enriched, system=base_system, max_tokens=requested)
        emit(
            'core.llm',
            elapsed_ms=(time.perf_counter() - llm_started) * 1000,
            tier=profile.tier,
            ok=True,
            output_chars=len(result or ''),
        )
        return result
    except Exception as exc:
        emit(
            'core.llm',
            elapsed_ms=(time.perf_counter() - llm_started) * 1000,
            tier=profile.tier,
            ok=False,
            error=str(exc)[:300],
        )
        if not _is_timeout_error(exc):
            raise
        retry = _retry_small(enriched, base_system)
        if retry:
            return retry
        return 'Não consegui obter uma resposta confiável para isso agora.'


hermes_core.llm = _contextual_llm


def _web_reply(text: str) -> str | None:
    try:
        from web_router import handle
        return handle(text)
    except Exception:
        return None


def _automation_reply(text: str) -> str | None:
    try:
        from cron_manager import handle
        return handle(text)
    except Exception:
        return None


def _devops_reply(text: str) -> str | None:
    # universal/assistant já concentram comandos operacionais suportados localmente.
    try:
        return handle_assistant_command(text) or handle_universal_command(text)
    except Exception:
        return None


def _call(handler: Callable[[str], str | None], text: str) -> str | None:
    try:
        return handler(text)
    except Exception:
        return None


def _brain_dispatch(text: str) -> tuple[str | None, str, dict | None]:
    """LLM decide intenção/contexto primeiro; parsers e routers só executam depois."""
    context = recent_conversation(limit=10, max_chars=4500)
    decision = brain_decide(text, context, _original_llm)
    if not decision or float(decision.get('confidence') or 0.0) < 0.55:
        return None, 'brain_fallback', decision

    route = str(decision.get('route') or 'chat')
    action = str(decision.get('action') or 'none')
    standalone = str(decision.get('standalone_request') or text).strip() or text

    emit(
        'core.brain',
        ok=True,
        route=route,
        action=action,
        mode=decision.get('mode'),
        confidence=decision.get('confidence'),
        references_previous_turn=decision.get('references_previous_turn'),
    )

    if route == 'chat':
        return None, 'brain_chat', decision

    if route == 'time':
        # Para mutações por referência natural, resolver assunto/contexto antes do parser temporal.
        if action in {'remove', 'pause', 'resume'}:
            reply = _call(handle_conversation_action, standalone)
            if reply is None and standalone != text:
                reply = _call(handle_conversation_action, text)
            if reply is not None:
                return reply, 'brain_time_context_action', decision
        reply = _call(handle_time_command, standalone)
        if reply is None and standalone != text:
            reply = _call(handle_time_command, text)
        return reply, 'brain_time', decision

    if route == 'automation':
        return _automation_reply(standalone), 'brain_automation', decision
    if route == 'finance':
        return _call(handle_finance_command, standalone), 'brain_finance', decision
    if route == 'research':
        return _web_reply(standalone), 'brain_research', decision
    if route == 'developer':
        return _call(handle_developer_command, standalone), 'brain_developer', decision
    if route == 'devops':
        return _devops_reply(standalone), 'brain_devops', decision
    if route == 'memory':
        return _call(handle_memory_command, standalone), 'brain_memory', decision
    if route == 'mission':
        return _call(handle_mission_command, standalone), 'brain_mission', decision
    if route == 'connected':
        return _call(handle_connected_command, standalone), 'brain_connected', decision
    if route == 'assistant':
        return _call(handle_assistant_command, standalone) or _call(handle_universal_command, standalone), 'brain_assistant', decision
    return None, 'brain_unknown', decision


def _legacy_fallback(text: str) -> tuple[str | None, str]:
    """Fallback semânticamente seguro para indisponibilidade/baixa confiança do brain."""
    # Ações conversacionais explícitas podem ser resolvidas sem LLM.
    conversational = _call(handle_conversation_action, text)
    if conversational is not None:
        return conversational, 'fallback_context_action'

    handlers: tuple[tuple[str, Callable[[str], str | None]], ...] = (
        ('finance', handle_finance_command),
        ('connected', handle_connected_command),
        ('assistant', handle_assistant_command),
        ('universal', handle_universal_command),
        ('mission', handle_mission_command),
        ('developer', handle_developer_command),
        ('memory', handle_memory_command),
        ('contextual', handle_contextual),
    )
    for name, handler in handlers:
        reply = _call(handler, text)
        if reply is not None:
            return reply, 'fallback_' + name
    web = _web_reply(text)
    if web is not None:
        return web, 'fallback_web'
    return None, 'fallback_llm'


def _persist_turn(text: str, reply: str) -> None:
    try:
        remember_turn('user', text)
        remember_turn('assistant', reply)
        append_daily('user', text)
        append_daily('assistant', reply)
    except Exception as exc:
        emit('core.persist', ok=False, error=str(exc)[:300])


def ask(text: str) -> str:
    text = text.strip()
    started = time.perf_counter()
    tid = trace_id()
    profile = classify_complexity(text)
    os.environ['HERMES_COMPLEXITY'] = profile.tier
    route_name = 'fallback_llm'

    direct = _deterministic_reply(text)
    if direct is not None:
        reply = direct
        route_name = 'deterministic_literal'
    else:
        brain_reply, brain_route, decision = _brain_dispatch(text)
        if brain_reply is not None:
            reply = brain_reply
            route_name = brain_route
        elif decision and decision.get('route') != 'chat':
            # O brain entendeu a intenção mas a ferramenta não conseguiu concluir.
            # O LLM responde sabendo o pedido autossuficiente, sem fingir execução.
            standalone = str(decision.get('standalone_request') or text)
            reply = hermes_core.ask(standalone)
            route_name = brain_route + '_explain'
        else:
            fallback_reply, fallback_route = _legacy_fallback(text)
            if fallback_reply is not None:
                reply = fallback_reply
                route_name = fallback_route
            else:
                reply = hermes_core.ask(text)
                route_name = 'chat_llm'

    _persist_turn(text, reply)
    emit(
        'core.total',
        elapsed_ms=(time.perf_counter() - started) * 1000,
        route=route_name,
        tier=profile.tier,
        input_chars=len(text),
        output_chars=len(reply or ''),
        trace=tid,
    )
    return reply


def main() -> int:
    if len(sys.argv) < 2:
        print('Hermes Core v5.0 — LLM-first Conversation Brain', flush=True)
        return 0
    try:
        print(ask(' '.join(sys.argv[1:])), flush=True)
        return 0
    except Exception as exc:
        emit('core.fatal', ok=False, error=str(exc)[:500])
        if _is_timeout_error(exc):
            print('Não consegui obter uma resposta confiável dentro do limite local.', flush=True)
            return 0
        print(f'Não consegui concluir essa solicitação. Detalhe: {exc}', flush=True)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
