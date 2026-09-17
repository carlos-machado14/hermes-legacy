from __future__ import annotations

import core_v2.day_overview as day


def test_overview_is_driven_by_structured_period(monkeypatch):
    monkeypatch.setattr(day, '_schedule_lines', lambda period: ['📅 Agenda', f'- period={period}'])
    monkeypatch.setattr(day, '_task_sections', lambda period: [f'✅ tasks={period}'])

    today = day.overview('today')
    tomorrow = day.overview('tomorrow')

    assert 'Seu dia hoje' in today
    assert 'period=today' in today
    assert 'tasks=today' in today
    assert 'Seu dia amanhã' in tomorrow
    assert 'period=tomorrow' in tomorrow
    assert 'tasks=tomorrow' in tomorrow


def test_day_overview_has_no_language_intent_classifier():
    assert not hasattr(day, 'is_generic_day_query')
    assert not hasattr(day, 'render')
