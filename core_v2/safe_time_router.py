from __future__ import annotations

import re

from temporal_parser import norm
from time_router import handle as _handle_time

_ACTION_HINTS = (
    'me lembre', 'lembre-me', 'me avise', 'me avisa', 'quero que me avise',
    'agende', 'agendar', 'crie um lembrete', 'crie uma rotina', 'marque ',
    'cancele', 'cancelar', 'cancela', 'remova', 'remover', 'apague', 'apagar',
    'pause', 'pausar', 'retome', 'retomar', 'mude ', 'altere ',
    'tenho reuniao', 'tenho compromisso', 'preciso ', 'tenho que ', 'devo ',
)
_QUERY_HINTS = (
    'agenda de hoje', 'agenda de amanha', 'minha agenda', 'meu cronograma',
    'o que tenho hoje', 'o que tenho amanha', 'meus lembretes', 'minhas rotinas',
    'quais lembretes', 'quantos alertas', 'quantos lembretes', 'tenho algum',
    'estamos com ', 'temos ', 'existe ', 'existem ', 'confere ',
)


def has_explicit_time_intent(text: str) -> bool:
    t = norm(text)
    if any(x in t for x in _ACTION_HINTS + _QUERY_HINTS):
        return True
    if '?' in str(text) and any(x in t for x in ('alerta', 'lembrete', 'agenda', 'rotina', 'evento', 'compromisso')):
        return True
    # IDs de agenda acompanhados de verbo de mutação também são explícitos.
    if re.search(r'\b[0-9a-f]{8,16}\b', t) and any(x in t for x in ('canc', 'remov', 'apag', 'paus', 'retom')):
        return True
    return False


def handle(text: str) -> str | None:
    if not has_explicit_time_intent(text):
        return None
    return _handle_time(text)
