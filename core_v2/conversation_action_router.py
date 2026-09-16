from __future__ import annotations

import re
from typing import Any

from conversation_memory import recent
from temporal_parser import norm
from time_store import latest_schedule, list_schedules, pause, remove, resume

_ACTIONS = {
    'remove': ('cancele', 'cancelar', 'cancela', 'remova', 'remover', 'remove', 'apague', 'apagar', 'apaga', 'exclua', 'excluir'),
    'pause': ('pause', 'pausar', 'pausa', 'pare', 'parar', 'suspenda', 'suspender'),
    'resume': ('retome', 'retomar', 'reative', 'reativar', 'continue', 'continuar'),
}
_STOP = {
    'o','a','os','as','um','uma','uns','umas','de','da','do','das','dos','que','eu','vc','voce','você',
    'me','meu','minha','meus','minhas','por','favor','lembrete','lembretes','rotina','rotinas','alerta','alertas',
    'evento','eventos','compromisso','compromissos','esse','essa','isso','aquele','aquela','aquilo','ele','ela',
    'primeiro','primeira','segundo','segunda','ultimo','ultima','último','última','agora','hoje','amanha','amanhã',
    'cancele','cancelar','cancela','remova','remover','remove','apague','apagar','apaga','exclua','excluir',
    'pause','pausar','pausa','pare','parar','suspenda','suspender','retome','retomar','reative','reativar','continue','continuar',
    'todas','todos','tudo','elas','eles',
}


def _action(text: str) -> str | None:
    t = norm(text)
    for action, words in _ACTIONS.items():
        if any(re.search(rf'\b{re.escape(norm(word))}\b', t) for word in words):
            return action
    return None


def _tokens(text: str) -> set[str]:
    return {
        token for token in re.findall(r'[a-z0-9à-ÿ]+', norm(text))
        if len(token) >= 2 and token not in _STOP
    }


def _recent_rows(limit: int = 12) -> list[dict[str, Any]]:
    return list(recent(limit=limit))


def _ids_from_recent() -> list[str]:
    ids: list[str] = []
    for row in reversed(_recent_rows()):
        text = str(row.get('text') or '')
        found = re.findall(r'\b(?:ID\s*)?([0-9a-f]{8,16})\b', text, re.I)
        for ref in found:
            if ref not in ids:
                ids.append(ref)
        if ids:
            break
    return ids


def _all_ids_from_last_assistant_list() -> list[str]:
    """Return IDs from the most recent assistant message that presented choices.

    This lets follow-ups such as "pode excluir todas elas" act on the exact set
    the assistant just showed, instead of invoking the LLM or guessing globally.
    """
    for row in reversed(_recent_rows(limit=20)):
        if row.get('role') != 'assistant':
            continue
        text = str(row.get('text') or '')
        ids = re.findall(r'\b(?:ID\s*)?([0-9a-f]{8,16})\b', text, re.I)
        unique: list[str] = []
        for ref in ids:
            if ref not in unique:
                unique.append(ref)
        if len(unique) >= 2:
            return unique
    return []


def _ordinal_ref(text: str) -> str | None:
    t = norm(text)
    ids = _ids_from_recent()
    if not ids:
        return None
    if any(x in t for x in ('primeiro', 'primeira', '1 ')):
        return ids[0]
    if any(x in t for x in ('segundo', 'segunda', '2 ')) and len(ids) >= 2:
        return ids[1]
    if any(x in t for x in ('ultimo', 'ultima')):
        return ids[-1]
    return None


def _recent_topic_tokens() -> set[str]:
    for row in reversed(_recent_rows()):
        if row.get('role') != 'user':
            continue
        tokens = _tokens(str(row.get('text') or ''))
        if tokens:
            return tokens
    return set()


def _score(tokens: set[str], item: dict[str, Any]) -> int:
    target = _tokens(str(item.get('message') or '') + ' ' + str(item.get('title') or ''))
    if not tokens or not target:
        return 0
    overlap = len(tokens & target)
    score = overlap * 5
    if tokens <= target:
        score += 8
    return score


def _is_bulk(text: str) -> bool:
    t = norm(text)
    return any(x in t for x in ('todas', 'todos', 'tudo', 'todas elas', 'todos eles'))


def _bulk_scope_ids(text: str) -> list[str]:
    """Resolve an explicit bulk request without relying on the model."""
    t = norm(text)

    # Pronoun follow-up: use exactly the choices shown by Hermes immediately before.
    if any(x in t for x in ('todas elas', 'todos eles', 'todas', 'todos')):
        contextual = _all_ids_from_last_assistant_list()
        if contextual and any(x in t for x in ('elas', 'eles')):
            return contextual

    items = list_schedules(status='active', limit=1000)
    if 'rotina' in t:
        return [str(item['id']) for item in items if str(item.get('kind') or '') == 'routine']
    if 'lembrete' in t or 'alerta' in t or 'aviso' in t:
        return [str(item['id']) for item in items if str(item.get('kind') or '') in {'reminder', 'alert'}]
    if 'evento' in t:
        return [str(item['id']) for item in items if str(item.get('kind') or '') == 'event']
    if 'compromisso' in t:
        return [str(item['id']) for item in items if str(item.get('kind') or '') == 'commitment']

    # Generic "excluir todas elas" after a list of choices.
    contextual = _all_ids_from_last_assistant_list()
    if contextual:
        return contextual
    return []


def _apply_bulk(action: str, refs: list[str]) -> str | None:
    if not refs:
        return None
    changed: list[dict[str, Any]] = []
    for ref in refs:
        try:
            if action == 'remove':
                changed.append(remove(ref))
            elif action == 'pause':
                changed.append(pause(ref))
            else:
                changed.append(resume(ref))
        except Exception:
            continue
    if not changed:
        return None

    verb = {'remove': 'Cancelei', 'pause': 'Pausei', 'resume': 'Retomei'}[action]
    noun = 'item' if len(changed) == 1 else 'itens'
    lines = [f"✅ {verb} {len(changed)} {noun}."]
    # Keep confirmation useful but compact.
    for item in changed[:8]:
        lines.append(f"- {item.get('message') or item.get('title')}")
    if len(changed) > 8:
        lines.append(f"- e mais {len(changed) - 8}")
    return '\n'.join(lines)


def _resolve(text: str) -> tuple[str | None, list[dict[str, Any]]]:
    raw = str(text or '').strip()
    direct = re.search(r'\b([0-9a-f]{8,16})\b', raw, re.I)
    if direct:
        return direct.group(1), []

    ordinal = _ordinal_ref(raw)
    if ordinal:
        return ordinal, []

    t = norm(raw)
    if any(x in t for x in ('esse', 'essa', 'isso', 'aquele', 'aquela', 'aquilo', 'o de agora', 'que fiz agora')):
        ids = _ids_from_recent()
        if len(ids) == 1:
            return ids[0], []

    tokens = _tokens(raw)
    if not tokens:
        tokens = _recent_topic_tokens()

    candidates: list[tuple[int, dict[str, Any]]] = []
    for item in list_schedules(status='active', limit=200):
        score = _score(tokens, item)
        if score > 0:
            candidates.append((score, item))
    candidates.sort(key=lambda pair: (pair[0], int(pair[1].get('created_at') or 0)), reverse=True)

    if candidates:
        best_score = candidates[0][0]
        best = [item for score, item in candidates if score == best_score]
        if len(best) == 1:
            return str(best[0].get('id')), []
        return None, best[:5]

    if any(x in t for x in ('ultimo', 'ultima', 'mais recente', 'de agora')):
        latest = latest_schedule()
        if latest:
            return str(latest.get('id')), []
    return None, []


def _ambiguous(action: str, rows: list[dict[str, Any]]) -> str:
    verb = {'remove':'cancelar', 'pause':'pausar', 'resume':'retomar'}[action]
    lines = [f'Encontrei mais de um lembrete que pode ser o que você quer {verb}:']
    for index, item in enumerate(rows, 1):
        lines.append(f"{index}. {item.get('message') or item.get('title')} [ID {item.get('id')}]")
    lines.append('Me diga qual deles pelo número, assunto ou ID — ou diga “todos”.')
    return '\n'.join(lines)


def handle(text: str) -> str | None:
    action = _action(text)
    if not action:
        return None

    if _is_bulk(text):
        bulk_reply = _apply_bulk(action, _bulk_scope_ids(text))
        if bulk_reply is not None:
            return bulk_reply

    ref, ambiguous = _resolve(text)
    if ambiguous:
        return _ambiguous(action, ambiguous)
    if not ref:
        return None

    try:
        if action == 'remove':
            item = remove(ref)
            return f"🗑️ Cancelei: {item.get('message') or item.get('title')}"
        if action == 'pause':
            item = pause(ref)
            return f"⏸️ Pausei: {item.get('message') or item.get('title')}"
        item = resume(ref)
        return f"▶️ Retomei: {item.get('message') or item.get('title')}"
    except Exception:
        return None
