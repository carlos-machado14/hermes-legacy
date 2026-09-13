#!/usr/bin/env python3
from __future__ import annotations

from memory_vault import retrieve, summary, sync_state_snapshots


def handle(text: str) -> str | None:
    t = text.strip(); low = t.lower()
    if low in {'status da memoria', 'status da memória', 'memoria do hermes', 'memória do hermes', 'memory vault'}:
        sync_state_snapshots()
        return summary()
    prefixes = ('buscar memoria ', 'buscar memória ', 'procure na memoria ', 'procure na memória ', 'lembra sobre ', 'o que lembra sobre ')
    for prefix in prefixes:
        if low.startswith(prefix):
            query = t[len(prefix):].strip()
            if not query:
                return 'Diga o assunto que você quer recuperar da memória.'
            sync_state_snapshots()
            found = retrieve(query, limit=5, max_chars=3200)
            return found or 'Não encontrei memória relevante sobre esse assunto.'
    return None
