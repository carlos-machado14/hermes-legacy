from core_v2.day_overview import is_generic_day_query


def test_generic_today_question_accepts_abbreviation():
    assert is_generic_day_query('Oq temos pra hoje?')


def test_generic_tomorrow_followup():
    assert is_generic_day_query('E amanhã?')


def test_specific_entity_stays_with_specialized_router():
    assert not is_generic_day_query('Quais rotinas temos hoje?')
    assert not is_generic_day_query('Quais tarefas tenho hoje?')


def test_mutation_is_not_read_fastpath():
    assert not is_generic_day_query('Cancela o que temos hoje')
