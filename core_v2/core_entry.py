#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time
from typing import Callable

import hermes_core
from assistant_router import handle as handle_assistant_command
from complexity_router import classify as classify_complexity
from connected_router import handle as handle_connected_command
from context_builder import compact as compact_context
from conversation_brain import decide as brain_decide
from conversation_memory import add as remember_turn, compact as recent_conversation
from developer_router import handle as handle_developer_command
from finance_router import handle as handle_finance_command
from intent_executor import execute as execute_intent
from memory_router import handle as handle_memory_command
from memory_vault import append_daily, retrieve as retrieve_memory, sync_state_snapshots
from mission_router import handle as handle_mission_command
from semantic_provider import llm as semantic_llm
from semantic_resilience import safe_read_fallback
from telemetry import emit, trace_id
from universal_router import handle as handle_universal_command

_original_llm = hermes_core.llm


def _is_timeout_error(exc: Exception) -> bool:
    text = str(exc).casefold()
    return any(k in text for k in ('timed out', 'timeout', 'readtimeout', 'pooltimeout', 'semantic provider unavailable'))


def _retry_small(prompt: str, system: str) -> str | None:
    try:
        previous = os.environ.get('HERMES_COMPLEXITY')
        os.environ['HERMES_COMPLEXITY'] = 'fast'
        return _original_llm(prompt, system=system, max_tokens=120)
    except Exception:
        return None
    finally:
        if previous is None:
            os.environ.pop('HERMES_COMPLEXITY', None)
        else:
            os.environ['HERMES_COMPLEXITY'] = previous


def _contextual_llm(prompt: str, system: str | None = None, max_tokens: int | None = None) -> str:
    profile = classify_complexity(prompt)
    os.environ['HERMES_COMPLEXITY'] = profile.tier

    context = ''
    long_term = ''
    context_started = time.perf_counter()
    if profile.use_personal and profile.personal_items > 0:
        context = compact_context(max_items=max(2, profile.personal_items))
        sync_state_snapshots()
        if profile.memory_limit > 0 and profile.memory_chars > 0:
            long_term = retrieve_memory(prompt, limit=profile.memory_limit, max_chars=profile.memory_chars)
    recent = recent_conversation(limit=10, max_chars=5000)
    context_ms = (time.perf_counter() - context_started) * 1000

    base_system = (
        'Você é Hermes, uma inteligência artificial pessoal. Responda em português do Brasil. '
        'Use a conversa recente e o estado disponível para manter continuidade. '
        'Entenda a intenção pelo significado, não por palavras-chave. '
        'Não invente dados, ações executadas ou ferramentas. Se faltar informação indispensável, peça somente o que falta.'
    )
    if system:
        base_system += '\n' + system

    sections: list[str] = []
    if recent:
        sections.append('CONVERSA RECENTE\n' + recent)
    if context:
        sections.append(context)
    if long_term:
        sections.append('MEMÓRIA RELEVANTE\n' + long_term)
    sections.append('MENSAGEM ATUAL\n' + prompt)
    enriched = '\n\n'.join(sections)
    requested = max_tokens or profile.max_output_tokens

    emit(
        'core.context',
        elapsed_ms=context_ms,
        tier=profile.tier,
        use_recent=bool(recent),
        use_personal=bool(context or long_term),
        prompt_chars=len(enriched),
        max_output_tokens=requested,
    )

    llm_started = time.perf_counter()
    try:
        result = _original_llm(enriched, system=base_system, max_tokens=requested)
        emit('core.llm', elapsed_ms=(time.perf_counter() - llm_started) * 1000, tier=profile.tier, ok=True, output_chars=len(result or ''))
        return result
    except Exception as exc:
        emit('core.llm', elapsed_ms=(time.perf_counter() - llm_started) * 1000, tier=profile.tier, ok=False, error=str(exc)[:300])
        if not _is_timeout_error(exc):
            raise
        retry = _retry_small(enriched, base_system)
        if retry:
            return retry
        return 'Não consegui responder com segurança agora. Tente novamente em alguns instantes.'


hermes_core.llm = _contextual_llm


def _call(handler: Callable[[str], str | None], text: str) -> str | None:
    try:
        return handler(text)
    except Exception:
        return None


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
    try:
        return handle_assistant_command(text) or handle_universal_command(text)
    except Exception:
        return None


def _capability_reply(route: str, standalone: str) -> str | None:
    handlers: dict[str, Callable[[str], str | None]] = {
        'finance': handle_finance_command,
        'developer': handle_developer_command,
        'memory': handle_memory_command,
        'mission': handle_mission_command,
        'connected': handle_connected_command,
        'assistant': handle_assistant_command,
    }
    if route == 'automation':
        return _automation_reply(standalone)
    if route == 'research':
        return _web_reply(standalone)
    if route == 'devops':
        return _devops_reply(standalone)
    handler = handlers.get(route)
    return _call(handler, standalone) if handler else None


def _brain_dispatch(text: str) -> tuple[str | None, str, dict | None]:
    context = recent_conversation(limit=6, max_chars=1800)
    started = time.perf_counter()
    try:
        decision = brain_decide(text, context, semantic_llm)
    except Exception as exc:
        emit(
            'core.brain', ok=False, route='unknown', action='none', reason='brain_exception',
            error=str(exc)[:300], timeout=_is_timeout_error(exc),
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
        return None, 'semantic_unavailable', None

    if not decision or float(decision.get('confidence') or 0.0) < 0.5:
        emit(
            'core.brain', ok=False, route='unknown', action='none',
            reason='unavailable_or_low_confidence', elapsed_ms=(time.perf_counter() - started) * 1000,
        )
        return None, 'semantic_unavailable', decision

    route = str(decision.get('route') or 'chat')
    action = str(decision.get('action') or 'none')
    standalone = str(decision.get('standalone_request') or text).strip() or text

    emit(
        'core.brain', ok=True, route=route, action=action, mode=decision.get('mode'),
        confidence=decision.get('confidence'),
        references_previous_turn=decision.get('references_previous_turn'),
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )

    try:
        structured_reply = execute_intent(decision, text)
    except Exception as exc:
        emit('core.intent_executor', ok=False, error=str(exc)[:300])
        structured_reply = None
    if structured_reply is not None:
        emit('core.intent_executor', ok=True, route=route, action=action)
        return structured_reply, 'structured_executor', decision

    response = str(decision.get('response') or '').strip()
    if route == 'chat' and response:
        return response, 'semantic_chat', decision

    capability = _capability_reply(route, standalone)
    if capability is not None:
        return capability, 'semantic_' + route, decision

    mutating = action in {'create', 'update', 'remove', 'pause', 'resume', 'run', 'execute', 'complete', 'reschedule'}
    if mutating:
        if response:
            return response, 'semantic_clarification', decision
        return 'Preciso de um pouco mais de contexto para executar isso com segurança.', 'semantic_clarification', decision

    return response or None, 'semantic_fallback', decision


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

    reply, route_name, decision = _brain_dispatch(text)

    if reply is None:
        safe_reply = safe_read_fallback(text)
        if safe_reply is not None:
            reply = safe_reply
            route_name = 'safe_read_resilience'

    # Se o cérebro semântico não conseguiu classificar, não fazemos uma segunda
    # espera longa no LLM geral. Isso evita transformar um SLA de poucos segundos
    # em 30-60 segundos de bloqueio. Consultas locais já tiveram chance no fallback.
    if reply is None and route_name == 'semantic_unavailable':
        reply = 'O cérebro semântico não respondeu a tempo. Não executei nenhuma ação para evitar fazer algo errado.'
        route_name = 'semantic_unavailable_fast'

    if reply is None:
        prompt = str(decision.get('standalone_request') or text) if decision else text
        reply = hermes_core.ask(prompt)
        route_name = 'semantic_general'

    _persist_turn(text, reply)
    emit(
        'core.total', elapsed_ms=(time.perf_counter() - started) * 1000,
        route=route_name, tier=profile.tier, input_chars=len(text),
        output_chars=len(reply or ''), trace=tid,
    )
    return reply


def main() -> int:
    if len(sys.argv) < 2:
        print('Hermes Core v6.4 — Fast Semantic Brain + Structured Executors', flush=True)
        return 0
    try:
        print(ask(' '.join(sys.argv[1:])), flush=True)
        return 0
    except Exception as exc:
        emit('core.fatal', ok=False, error=str(exc)[:500])
        if _is_timeout_error(exc):
            print('Não consegui responder com segurança agora. Tente novamente em alguns instantes.', flush=True)
            return 0
        print(f'Não consegui concluir essa solicitação. Detalhe: {exc}', flush=True)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
