from __future__ import annotations

from core_v2 import local_action_intent
from core_v2.day_overview import is_generic_day_query


def test_generic_day_query_is_understood():
    assert is_generic_day_query('Oq temos pra hoje?')
    assert is_generic_day_query('E amanhã?')


def test_plural_internal_action_is_semantic_not_exact_phrase(monkeypatch):
    rows = [
        {'id': 'a1', 'kind': 'reminder', 'status': 'active', 'title': 'Enviar relatório'},
        {'id': 'b2', 'kind': 'alert', 'status': 'active', 'title': 'Ligar para cliente'},
    ]
    monkeypatch.setattr(local_action_intent, 'list_schedules', lambda **kwargs: rows)
    changed = []
    monkeypatch.setattr(local_action_intent, 'remove', lambda ref: changed.append(ref) or next(x for x in rows if x['id'] == ref))

    reply = local_action_intent.handle('cancele nossos lembretes')
    assert changed == ['a1', 'b2']
    assert reply == '✅ Cancelei 2 lembretes.'


def test_singular_action_stays_for_semantic_brain(monkeypatch):
    rows = [{'id': 'a1', 'kind': 'reminder', 'status': 'active', 'title': 'Enviar relatório'}]
    monkeypatch.setattr(local_action_intent, 'list_schedules', lambda **kwargs: rows)
    assert local_action_intent.handle('cancele o lembrete do relatório') is None
