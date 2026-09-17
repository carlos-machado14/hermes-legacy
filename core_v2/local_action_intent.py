from __future__ import annotations

import re
from typing import Any

from temporal_parser import norm
from time_store import list_schedules, pause, remove, resume

_ACTION_STEMS = {
    'remove': ('cancel', 'exclu', 'remov', 'apag'),
    'pause': ('paus', 'suspend', 'par'),
    'resume': ('retom', 'reativ', 'continu'),
}
_ENTITY_KINDS = {
    'rotina': {'routine'},
    'rotinas': {'routine'},
    'lembrete': {'reminder', 'alert'},
    'lembretes': {'reminder', 'alert'},
    'alerta': {'alert'},
    'alertas': {'alert'},
    'evento': {'event'},
    'eventos': {'event'},
    'compromisso': {'commitment'},
    'compromissos': {'commitment'},
}


def _action(t: str) -> str | None:
    for action, stems in _ACTION_STEMS.items():
        if any(stem in t for stem in stems):
            return action
    return None


def _entity(t: str) -> tuple[set[str] | None, bool]:
    tokens = set(re.findall(r'[a-z0-9à-ÿ]+', t))
    for word, kinds in _ENTITY_KINDS.items():
        if word in tokens:
            return kinds, word.endswith('s')
    return None, False


def _label(item: dict[str, Any]) -> str:
    text = str(item.get('title') or item.get('message') or 'item').strip()
    if 'agua' in norm(text):
        return 'Tomar água'
    return text[:110]


def handle(text: str) -> str | None:
    """Fallback local para mutações internas simples por intenção gramatical.

    Não depende de frases exatas. Reconhece ação verbal + entidade local. Só atua
    em agenda interna do Hermes e nunca em ações externas.
    """
    raw = str(text or '').strip()
    if not raw:
        return None
    t = norm(raw)
    action = _action(t)
    kinds, plural = _entity(t)
    if not action or kinds is None:
        return None

    rows = list_schedules(status='active' if action != 'resume' else None, limit=1000)
    rows = [x for x in rows if str(x.get('kind') or '') in kinds]
    if action == 'resume':
        rows = [x for x in rows if str(x.get('status') or '') == 'paused']
    if not rows:
        return 'Não encontrei itens ativos desse tipo.'

    # Plural sem referência específica significa a coleção da categoria. Singular
    # continua para o cérebro, que resolve assunto/contexto com mais precisão.
    reference_words = set(re.findall(r'[a-z0-9à-ÿ]+', t)) - {
        'meu','minha','meus','minhas','nosso','nossa','nossos','nossas','todos','todas',
        'os','as','o','a','de','do','da','por','favor',
    }
    entity_words = set(_ENTITY_KINDS.keys())
    action_words = {w for stems in _ACTION_STEMS.values() for w in stems}
    meaningful = [w for w in reference_words if w not in entity_words and not any(w.startswith(stem) for stem in action_words)]

    bulk = plural and not meaningful
    if not bulk:
        return None

    changed: list[dict[str, Any]] = []
    for item in rows:
        try:
            if action == 'remove':
                changed.append(remove(str(item['id'])))
            elif action == 'pause':
                changed.append(pause(str(item['id'])))
            else:
                changed.append(resume(str(item['id'])))
        except Exception:
            continue
    if not changed:
        return None

    verb = {'remove': 'Cancelei', 'pause': 'Pausei', 'resume': 'Retomei'}[action]
    noun = 'lembretes' if kinds & {'reminder', 'alert'} else 'rotinas' if kinds == {'routine'} else 'itens'
    return f"✅ {verb} {len(changed)} {noun}."
