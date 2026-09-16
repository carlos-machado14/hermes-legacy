from __future__ import annotations

import subconscious_router


def test_detects_natural_routine_query_at_clock(monkeypatch):
    monkeypatch.setattr(subconscious_router, 'list_schedules', lambda **kwargs: [])
    reply = subconscious_router.handle('quais as rotinas que temos as 17h?')
    assert reply is not None
    assert '17:00' in reply


def test_does_not_intercept_mutation():
    assert subconscious_router.handle('cancela a rotina da água') is None


def test_does_not_intercept_unrelated_chat():
    assert subconscious_router.handle('o que você acha desse projeto?') is None
