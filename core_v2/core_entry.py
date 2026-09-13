#!/usr/bin/env python3
from __future__ import annotations

import sys

import hermes_core
from context_builder import compact as compact_context
from contextual_router import handle as handle_contextual
from conversation_memory import add as remember_turn, compact as recent_conversation
from memory_router import handle as handle_memory_command
from memory_vault import append_daily, retrieve as retrieve_memory, sync_state_snapshots
from developer_router import handle as handle_developer_command

_original_llm = hermes_core.llm


def _is_timeout_error(exc: Exception) -> bool:
    text = str(exc).casefold()
    return any(k in text for k in ('timed out', 'timeout', 'readtimeout', 'pooltimeout'))


def _contextual_llm(prompt: str, system: str | None = None, max_tokens: int | None = None) -> str:
    context = compact_context(max_items=3)
    recent = recent_conversation(limit=4, max_chars=1600)
    sync_state_snapshots()
    long_term = retrieve_memory(prompt, limit=3, max_chars=1400)
    enriched = (
        f"{context}\n\n"
        f"CONVERSA RECENTE\n{recent}\n\n"
        f"MEMÓRIA RELEVANTE\n{long_term or 'Nenhuma memória adicional relevante.'}\n\n"
        f"MENSAGEM ATUAL\n{prompt}\n\n"
        "Responda considerando referências como isso, ele, essa ideia, aquele plano e esse objetivo. "
        "Continue o assunto sem pedir novamente dados já disponíveis. Seja direto e útil. "
        "Nunca encerre a resposta no meio de uma frase ou item; conclua o raciocínio."
    )
    low = prompt.lower()
    requested = max_tokens
    if requested is None:
        requested = 520 if any(k in low for k in ('detalhadamente', 'completo', 'completa', 'passo a passo', 'aprofund')) else 320
    try:
        return _original_llm(enriched, system=system, max_tokens=requested)
    except Exception as exc:
        if not _is_timeout_error(exc):
            raise
        return (
            'Demorei mais do que deveria para gerar essa resposta. Mantive o contexto e sua mensagem registrada. '
            'Vou priorizar uma resposta mais curta/objetiva na próxima interação em vez de perder a conversa.'
        )


hermes_core.llm = _contextual_llm


def ask(text: str) -> str:
    text = text.strip()
    developer_reply = handle_developer_command(text)
    if developer_reply is not None:
        reply = developer_reply
    else:
        memory_reply = handle_memory_command(text)
        if memory_reply is not None:
            reply = memory_reply
        else:
            contextual = handle_contextual(text)
            if contextual is not None:
                reply = contextual
            else:
                reply = hermes_core.ask(text)
    remember_turn('user', text)
    remember_turn('assistant', reply)
    append_daily('user', text)
    append_daily('assistant', reply)
    return reply


def main() -> int:
    if len(sys.argv) < 2:
        print('Hermes Core conversational entry + Memory Vault + GitHub Workspace', flush=True)
        return 0
    try:
        print(ask(' '.join(sys.argv[1:])), flush=True)
        return 0
    except Exception as exc:
        if _is_timeout_error(exc):
            print(
                'Demorei mais do que deveria para responder, mas mantive o contexto. '
                'Sua mensagem não foi perdida.',
                flush=True,
            )
            return 0
        print(f'Não consegui concluir essa resposta agora, mas o contexto foi preservado. Detalhe: {exc}', flush=True)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
