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
    }


def test_cancel_all_schedule_uses_structured_scope(monkeypatch):
    rows = [
        _schedule('aaaaaaaa1111', 'routine', 'tomar agua minha meta é 4l a cada 15 min'),
        _schedule('bbbbbbbb2222', 'reminder', 'enviar atualização para André'),
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
    reply = ex.execute(decision, 'cancele toda minha agenda hoje e futura')
    assert cancelled == ['aaaaaaaa1111', 'bbbbbbbb2222', 'cccccccc3333']
    assert '3 itens' in reply


def test_cancel_all_reminders_includes_notification_routines(monkeypatch):
    rows = [
        _schedule('aaaaaaaa1111', 'routine', 'tomar água a cada 15 min'),
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
    reply = ex.execute(decision, 'cancele nossos lembretes')
    assert cancelled == ['aaaaaaaa1111', 'bbbbbbbb2222']
    assert '2 itens' in reply
    assert 'Tomar água' in reply


def test_single_reference_is_resolved_from_structured_reference(monkeypatch):
    rows = [
        _schedule('aaaaaaaa1111', 'routine', 'tomar água a cada 15 min'),
        _schedule('bbbbbbbb2222', 'reminder', 'enviar atualização para André'),
    ]
    monkeypatch.setattr(ex, 'list_schedules', lambda **kwargs: list(rows))
    monkeypatch.setattr(ex, 'remove', lambda ref: next(x for x in rows if x['id'] == ref))
    decision = {
        'route': 'time',
        'action': 'remove',
        'target': {'entity': 'reminder', 'scope': 'single', 'reference': 'atualização do André', 'ids': [], 'filters': {}},
    }
    reply = ex.execute(decision, 'tira o do André')
    assert 'André' in reply
