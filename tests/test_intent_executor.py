from __future__ import annotations

import intent_executor as ex


def _schedule(i: str, kind: str, message: str) -> dict:
    return {
        'id': i,
        'kind': kind,
        'message': message,
        'title': message,
        'status': 'active',
        'created_at': 1,
        'timezone': 'America/Sao_Paulo',
        'recurrence': {'freq': 'daily', 'time': '09:00'},
    }


def test_cancel_all_schedule_uses_structured_scope(monkeypatch):
    rows = [
        _schedule('aaaaaaaa1111', 'routine', 'hidratação'),
        _schedule('bbbbbbbb2222', 'reminder', 'enviar atualização'),
        _schedule('cccccccc3333', 'event', 'reunião do projeto'),
    ]
    monkeypatch.setattr(ex, 'list_schedules', lambda **kwargs: list(rows))
    cancelled = []

    def fake_remove(ref):
        cancelled.append(ref)
        return next(x for x in rows if x['id'] == ref)

    monkeypatch.setattr(ex, 'remove', fake_remove)
    decision = {
        'route': 'time',
        'action': 'remove',
        'target': {'entity': 'schedule', 'scope': 'all', 'reference': '', 'ids': [], 'filters': {}},
    }
    reply = ex.execute(decision, 'qualquer formulação natural')
    assert cancelled == ['aaaaaaaa1111', 'bbbbbbbb2222', 'cccccccc3333']
    assert '3 itens' in reply


def test_cancel_reminder_category_is_driven_by_ontology(monkeypatch):
    rows = [
        _schedule('aaaaaaaa1111', 'routine', 'hidratação'),
        _schedule('bbbbbbbb2222', 'reminder', 'enviar atualização'),
        _schedule('cccccccc3333', 'event', 'reunião'),
    ]
    monkeypatch.setattr(ex, 'list_schedules', lambda **kwargs: list(rows))
    cancelled = []

    def fake_remove(ref):
        cancelled.append(ref)
        return next(x for x in rows if x['id'] == ref)

    monkeypatch.setattr(ex, 'remove', fake_remove)
    decision = {
        'route': 'time',
        'action': 'remove',
        'target': {'entity': 'reminder', 'scope': 'all', 'reference': '', 'ids': [], 'filters': {}},
    }
    reply = ex.execute(decision, 'texto irrelevante para o executor')
    assert cancelled == ['aaaaaaaa1111', 'bbbbbbbb2222']
    assert '2 itens' in reply


def test_single_reference_uses_language_agnostic_similarity(monkeypatch):
    rows = [
        _schedule('aaaaaaaa1111', 'routine', 'hidratação durante o expediente'),
        _schedule('bbbbbbbb2222', 'reminder', 'enviar atualização para André'),
    ]
    monkeypatch.setattr(ex, 'list_schedules', lambda **kwargs: list(rows))
    monkeypatch.setattr(ex, 'remove', lambda ref: next(x for x in rows if x['id'] == ref))
    decision = {
        'route': 'time',
        'action': 'remove',
        'target': {'entity': 'reminder', 'scope': 'single', 'reference': 'enviar atualização para André', 'ids': [], 'filters': {}},
    }
    reply = ex.execute(decision, 'texto não usado para descobrir a ação')
    assert 'André' in reply


def test_ids_take_priority_over_reference(monkeypatch):
    rows = [
        _schedule('aaaaaaaa1111', 'reminder', 'um'),
        _schedule('bbbbbbbb2222', 'reminder', 'dois'),
    ]
    monkeypatch.setattr(ex, 'list_schedules', lambda **kwargs: list(rows))
    monkeypatch.setattr(ex, 'remove', lambda ref: next(x for x in rows if x['id'] == ref))
    decision = {
        'route': 'time',
        'action': 'remove',
        'target': {'entity': 'reminder', 'scope': 'single', 'reference': '', 'ids': ['bbbbbbbb2222'], 'filters': {}},
    }
    reply = ex.execute(decision, 'qualquer coisa')
    assert 'dois' in reply
