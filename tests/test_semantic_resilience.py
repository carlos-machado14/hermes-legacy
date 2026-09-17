from __future__ import annotations

from datetime import date

import core_v2.semantic_resilience as sr
from core_v2.temporal_query import TemporalRange


def test_temporal_question_can_fall_back_to_day_overview(monkeypatch):
    monkeypatch.setattr(sr, 'resolve_temporal_range', lambda text: TemporalRange(date(2026, 9, 17), date(2026, 9, 17), 'hoje'))
    monkeypatch.setattr(sr, 'overview_range', lambda start, end, label: f'OVERVIEW:{label}')
    assert sr.safe_read_fallback('oq temos para hoje?') == 'OVERVIEW:hoje'


def test_nominal_temporal_read_without_question_mark(monkeypatch):
    monkeypatch.setattr(sr, 'resolve_temporal_range', lambda text: TemporalRange(date(2026, 9, 21), date(2026, 9, 27), 'semana que vem'))
    monkeypatch.setattr(sr, 'overview_range', lambda start, end, label: f'OVERVIEW:{label}')
    assert sr.safe_read_fallback('Agenda - semana que vem') == 'OVERVIEW:semana que vem'


def test_mutation_is_never_masked_as_read_fallback(monkeypatch):
    called = []
    monkeypatch.setattr(sr, 'resolve_temporal_range', lambda text: called.append(text) or TemporalRange(date(2026, 9, 17), date(2026, 9, 17), 'hoje'))
    assert sr.safe_read_fallback('cancele todos os meus lembretes de hoje') is None
    assert called == []


def test_unresolved_question_does_not_guess(monkeypatch):
    monkeypatch.setattr(sr, 'resolve_temporal_range', lambda text: None)
    assert sr.safe_read_fallback('qual é a capital da Itália?') is None
