from datetime import datetime
from zoneinfo import ZoneInfo

from complexity_router import classify
from temporal_parser import parse


def test_interval_accepts_min_abbreviation():
    now = datetime(2026, 9, 16, 7, 0, tzinfo=ZoneInfo('America/Sao_Paulo'))
    parsed = parse(
        'Quero que vc me avise todos os dias da semana entre as 8 e as 17h para lembrar de tomar agua a cada 15 min',
        now=now,
    )
    recurrence = parsed['recurrence']
    assert recurrence['freq'] == 'interval'
    assert recurrence['minutes'] == 15
    assert recurrence['window_start'] == '08:00'
    assert recurrence['window_end'] == '17:00'


def test_normal_messages_keep_recent_context():
    profile = classify('cancela o da agua')
    assert profile.use_recent is True
    assert profile.recent_items >= 2
