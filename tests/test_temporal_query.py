from datetime import date

from core_v2.temporal_query import resolve_temporal_range


TODAY = date(2026, 9, 17)  # quinta-feira


def test_today_and_tomorrow():
    assert resolve_temporal_range('o que temos para hoje?', today=TODAY).start == date(2026, 9, 17)
    assert resolve_temporal_range('e amanhã?', today=TODAY).start == date(2026, 9, 18)


def test_explicit_numeric_date():
    period = resolve_temporal_range('qual minha agenda do dia 25/09?', today=TODAY)
    assert period.start == date(2026, 9, 25)
    assert period.end == date(2026, 9, 25)


def test_day_of_month():
    assert resolve_temporal_range('o que tenho dia 25?', today=TODAY).start == date(2026, 9, 25)


def test_weekday():
    assert resolve_temporal_range('o que tenho sexta?', today=TODAY).start == date(2026, 9, 18)
    assert resolve_temporal_range('o que tenho sexta da semana que vem?', today=TODAY).start == date(2026, 9, 25)


def test_next_week():
    period = resolve_temporal_range('qual minha agenda da semana que vem?', today=TODAY)
    assert period.start == date(2026, 9, 21)
    assert period.end == date(2026, 9, 27)


def test_named_month_and_relative_days():
    assert resolve_temporal_range('o que tenho dia 25 de setembro?', today=TODAY).start == date(2026, 9, 25)
    assert resolve_temporal_range('o que tenho daqui a 10 dias?', today=TODAY).start == date(2026, 9, 27)
