from delivery import _compact_time_notification


def test_water_routine_is_concise():
    raw = '🔔 Rotina\ntomar agua minha meta é 4l preciso tomar agua a cada 15 min'
    assert _compact_time_notification(raw) == '💧 Hora de tomar água'


def test_normal_message_is_not_changed():
    raw = 'Hermes — plano do dia\nAgenda e tarefas'
    assert _compact_time_notification(raw) == raw
