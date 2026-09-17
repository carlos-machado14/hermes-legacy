from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import core_v2.semantic_resilience as sr


def test_temporal_question_can_fall_back_to_day_overview(monkeypatch):
    zone = ZoneInfo('America/Sao_Paulo')
    today = datetime.now(zone).replace(hour=9, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(sr, 'parse', lambda text: {
        'timezone': 'America/Sao_Paulo',
        'next_run_at': int(today.timestamp()),
        'recurrence': {'freq': 'once', 'at': today.isoformat()},
    })
    monkeypatch.setattr(sr, 'overview', lambda period: f'OVERVIEW:{period}')

    assert sr.safe_read_fallback('oq temos para hoje?') == 'OVERVIEW:today'


def test_fallback_never_executes_non_question(monkeypatch):
    called = []
    monkeypatch.setattr(sr, 'parse', lambda text: called.append(text) or None)
    assert sr.safe_read_fallback('cancele tudo hoje') is None
    assert called == []


def test_unresolved_question_does_not_guess(monkeypatch):
    monkeypatch.setattr(sr, 'parse', lambda text: None)
    assert sr.safe_read_fallback('qual é a capital da Itália?') is None
