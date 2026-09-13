#!/usr/bin/env python3
from __future__ import annotations

import sys

import hermes_core
from context_builder import compact as compact_context
from contextual_router import handle as handle_contextual
from conversation_memory import add as remember_turn, compact as recent_conversation

_original_llm = hermes_core.llm


def _contextual_llm(prompt: str, system: str | None = None, max_tokens: int | None = None) -> str:
    context = compact_context(max_items=4)
    recent = recent_conversation(limit=6, max_chars=3200)
    enriched = (
        f"{context}\n\n"
        f"CONVERSA RECENTE\n{recent}\n\n"
        f"MENSAGEM ATUAL\n{prompt}\n\n"
        "Responda considerando referências como isso, ele, essa ideia, aquele plano e esse objetivo. "
        "Se o usuário estiver continuando um assunto, não reinicie a conversa nem peça dados já disponíveis."
    )
    # Conversa comum deve ser rápida. Só pedidos explicitamente detalhados usam teto maior.
    low = prompt.lower()
    requested = max_tokens
    if requested is None:
        requested = 760 if any(k in low for k in ('detalhadamente', 'completo', 'completa', 'passo a passo', 'aprofund')) else 420
    return _original_llm(enriched, system=system, max_tokens=requested)


hermes_core.llm = _contextual_llm


def ask(text: str) -> str:
    text = text.strip()
    # O histórico anterior já está disponível antes de inserir a mensagem atual.
    contextual = handle_contextual(text)
    if contextual is not None:
        reply = contextual
    else:
        reply = hermes_core.ask(text)
    remember_turn('user', text)
    remember_turn('assistant', reply)
    return reply


def main() -> int:
    if len(sys.argv) < 2:
        print('Hermes Core conversational entry', flush=True)
        return 0
    try:
        print(ask(' '.join(sys.argv[1:])), flush=True)
        return 0
    except Exception as exc:
        print(f'Erro no Hermes Core: {exc}', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
