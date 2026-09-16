from conversation_brain import decide


def _fake(payload: str):
    def llm(prompt: str, **_: object) -> str:
        return payload
    return llm


def test_followup_tomorrow_becomes_standalone_time_query():
    out = decide(
        'e amanhã?',
        'Usuário: quais lembretes eu tenho hoje?\nHermes: você tem 2 lembretes hoje.',
        _fake('{"mode":"followup","route":"time","action":"list","standalone_request":"mostrar minha agenda de amanhã","references_previous_turn":true,"confidence":0.97,"reason":"continuação da agenda"}'),
    )
    assert out is not None
    assert out['route'] == 'time'
    assert out['action'] == 'list'
    assert out['references_previous_turn'] is True
    assert 'amanhã' in out['standalone_request']


def test_cancel_by_topic_uses_previous_context():
    out = decide(
        'cancela o da água',
        'Usuário: me lembre de tomar água a cada 15 min entre 8 e 17h\nHermes: rotina criada.',
        _fake('{"mode":"followup","route":"time","action":"remove","standalone_request":"cancelar lembrete de tomar água","references_previous_turn":true,"confidence":0.99,"reason":"referência ao lembrete anterior"}'),
    )
    assert out is not None
    assert out['action'] == 'remove'
    assert 'água' in out['standalone_request']


def test_question_cannot_be_validated_as_mutating_action():
    out = decide(
        'temos dois alertas hoje às 8:30?',
        '',
        _fake('{"mode":"query","route":"time","action":"create","standalone_request":"criar dois alertas hoje às 8:30","references_previous_turn":false,"confidence":0.92,"reason":"errado"}'),
    )
    assert out is None


def test_normal_chat_stays_chat():
    out = decide(
        'o que você acha dessa ideia?',
        'Usuário: estou pensando em melhorar o projeto.',
        _fake('{"mode":"chat","route":"chat","action":"none","standalone_request":"o que você acha dessa ideia?","references_previous_turn":true,"confidence":0.93,"reason":"conversa"}'),
    )
    assert out is not None
    assert out['route'] == 'chat'
    assert out['action'] == 'none'
