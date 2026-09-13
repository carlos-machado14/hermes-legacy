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


def _contextual_llm(prompt: str, system: str | None = None, max_tokens: int | None = None) -> str:
    context = compact_context(max_items=4)
    recent = recent_conversation(limit=6, max_chars=2800)
    sync_state_snapshots()
    long_term = retrieve_memory(prompt, limit=4, max_chars=2600)
    enriched = (
        f"{context}\n\n"
        f"CONVERSA RECENTE\n{recent}\n\n"
        f"MEMÓRIA DE LONGO PRAZO RELEVANTE\n{long_term or 'Nenhuma memória adicional relevante.'}\n\n"
        f"MENSAGEM ATUAL\n{prompt}\n\n"
        "Responda considerando referências como isso, ele, essa ideia, aquele plano e esse objetivo. "
        "Se o usuário estiver continuando um assunto, não reinicie a conversa nem peça dados já disponíveis. "
        "Use somente as memórias relevantes acima; não presuma que todo o vault precisa ser carregado."
    )
    low = prompt.lower()
    requested = max_tokens
    if requested is None:
        requested = 760 if any(k in low for k in ('detalhadamente', 'completo', 'completa', 'passo a passo', 'aprofund')) else 420
    return _original_llm(enriched, system=system, max_tokens=requested)


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
        print(f'Erro no Hermes Core: {exc}', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
