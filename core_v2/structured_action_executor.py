from __future__ import annotations

from typing import Any

from time_store import list_schedules, pause, remove, resume


def _kinds(entity: str) -> set[str] | None:
    e = str(entity or '').strip().casefold()
    mapping = {
        'routine': {'routine'},
        'reminder': {'reminder', 'alert'},
        'alert': {'alert'},
        'event': {'event'},
        'commitment': {'commitment'},
        'schedule': None,
    }
    return mapping.get(e)


def _label(item: dict[str, Any]) -> str:
    text = str(item.get('title') or item.get('message') or 'item').strip()
    if 'agua' in text.casefold() or 'água' in text.casefold():
        return 'Tomar água'
    return text[:120]


def execute_time_decision(decision: dict[str, Any]) -> str | None:
    """Executa intenção temporal já estruturada pelo cérebro.

    Não interpreta linguagem natural aqui. Recebe ação/alvo/escopo estáveis e
    apenas aplica a mutação sobre o estado local.
    """
    action = str(decision.get('action') or '').casefold()
    if action not in {'remove', 'pause', 'resume'}:
        return None

    target = decision.get('target') if isinstance(decision.get('target'), dict) else {}
    entity = str(target.get('entity') or 'schedule').casefold()
    scope = str(target.get('scope') or 'unknown').casefold()
    ids = [str(x) for x in (target.get('ids') or []) if x]
    reference = str(target.get('reference') or '').strip().casefold()

    rows = list_schedules(status='active' if action != 'resume' else None, limit=1000)
    kinds = _kinds(entity)
    if kinds is not None:
        rows = [x for x in rows if str(x.get('kind') or '') in kinds]

    selected: list[dict[str, Any]] = []
    if ids:
        wanted = set(ids)
        selected = [x for x in rows if str(x.get('id') or '') in wanted or any(str(x.get('id') or '').startswith(i) for i in wanted)]
    elif scope == 'all':
        selected = rows
    elif reference:
        terms = [x for x in reference.replace('-', ' ').split() if len(x) >= 3]
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in rows:
            hay = (str(item.get('title') or '') + ' ' + str(item.get('message') or '')).casefold()
            score = sum(1 for term in terms if term in hay)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda x: (x[0], int(x[1].get('created_at') or 0)), reverse=True)
        if scored:
            best = scored[0][0]
            selected = [item for score, item in scored if score == best]
            if scope == 'single' and selected:
                selected = selected[:1]

    if not selected:
        return None

    changed: list[dict[str, Any]] = []
    for item in selected:
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
    if len(changed) == 1:
        return f"✅ {verb}: {_label(changed[0])}."
    noun = 'lembretes' if entity in {'reminder', 'alert'} else 'rotinas' if entity == 'routine' else 'itens'
    return f"✅ {verb} {len(changed)} {noun}."
