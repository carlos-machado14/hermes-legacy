from __future__ import annotations

import task_router
from local_fastpath import handle


def test_natural_task_question_does_not_need_llm(monkeypatch):
    monkeypatch.setattr(task_router, 'list_tasks', lambda status=None, goal_id=None: [
        {
            'id': 'abc123def0',
            'title': 'Enviar atualizações para o André',
            'status': 'todo',
            'priority': 'high',
            'due': None,
            'updated_at': 1,
        }
    ])
    reply = handle('quais tarefas eu tenho hoje?')
    assert reply is not None
    assert 'Enviar atualizações para o André' in reply
    assert 'Tarefas pendentes' in reply


def test_unrelated_chat_does_not_hit_fastpath():
    assert handle('o que você acha dessa ideia?') is None
