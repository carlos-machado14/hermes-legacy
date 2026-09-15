from __future__ import annotations

import json
import re
import time
from typing import Any

import hermes_core
from goal_manager import list_goals
from task_manager import create_task, list_tasks


def _json(raw: str) -> list[dict[str, Any]]:
    text = str(raw or '').strip()
    try:
        data = json.loads(text)
    except Exception:
        m = re.search(r'\[.*\]', text, re.S)
        if not m: return []
        try: data = json.loads(m.group(0))
        except Exception: return []
    return data if isinstance(data, list) else []


def _norm(text: str) -> str:
    return re.sub(r'\W+', ' ', str(text or '').casefold()).strip()


def discover(limit: int = 5) -> list[dict[str, Any]]:
    goals = list_goals(include_done=False)[:3]
    if not goals: return []
    existing = list_tasks()
    existing_titles = {_norm(str(t.get('title') or '')) for t in existing if t.get('status') != 'done'}
    created: list[dict[str, Any]] = []

    for goal in goals:
        if len(created) >= limit: break
        goal_id = str(goal.get('id') or '')
        prompt = (
            'OBJETIVO ATIVO DO USUÁRIO:\n'
            f"{goal.get('title')}\nNotas: {goal.get('notes') or ''}\nPrazo: {goal.get('deadline') or 'não definido'}\n\n"
            'Proponha no máximo 3 ações INTERNAS, de baixo risco, que o Hermes possa executar sozinho agora para aproximar o usuário desse objetivo. '
            'Prefira pesquisar informações úteis, comparar opções, preparar análises, detectar oportunidades ou organizar dados. '
            'Não proponha enviar mensagens, comprar, publicar, deletar, fazer deploy, alterar produção ou contatar pessoas. '
            'Cada ação deve ter utilidade concreta e não ser genérica. '
            'Retorne SOMENTE JSON array: [{"title":"...","kind":"research|analysis","reason":"...","relevance":0-100}]'
        )
        try:
            raw = hermes_core.llm(prompt, system='Você é o motor de iniciativa do Hermes. Seja conservador, útil e orientado ao objetivo.', max_tokens=420)
        except Exception:
            continue
        for item in _json(raw):
            if len(created) >= limit: break
            if not isinstance(item, dict): continue
            title = str(item.get('title') or '').strip()
            kind = str(item.get('kind') or '').strip().lower()
            relevance = int(item.get('relevance') or 0)
            if not title or kind not in {'research','analysis'} or relevance < 70: continue
            key = _norm(title)
            if not key or key in existing_titles: continue
            task = create_task(
                title,
                goal_id=goal_id,
                priority='medium' if relevance < 90 else 'high',
                kind=kind,
                metadata={
                    'source':'hermes-initiative', 'initiative_goal':goal_id,
                    'reason':str(item.get('reason') or '')[:600], 'relevance':relevance,
                    'created_at':int(time.time()),
                },
            )
            existing_titles.add(key); created.append(task)
    return created
