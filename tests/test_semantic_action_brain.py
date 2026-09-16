from core_v2.conversation_brain import decide


def test_followup_selection_is_semantic_not_phrase_bound():
    def fake_llm(prompt, system=None, max_tokens=None):
        return '''{
          "mode":"followup",
          "route":"time",
          "action":"remove",
          "standalone_request":"cancelar os itens apresentados na última lista",
          "references_previous_turn":true,
          "target":{"entity":"schedule","scope":"selection","reference":"itens da última lista","ids":["7ae7a7820a","5e3c663198"],"filters":{}},
          "confidence":0.97,
          "reason":"o usuário se refere ao conjunto listado imediatamente antes"
        }'''

    context = (
        'assistant: 1. lembrete A [ID 7ae7a7820a]\n'
        'assistant: 2. rotina B [ID 5e3c663198]\n'
    )
    result = decide('não quero mais nenhuma dessas, tira tudo daí', context, fake_llm)
    assert result is not None
    assert result['action'] == 'remove'
    assert result['target']['scope'] == 'selection'
    assert result['target']['ids'] == ['7ae7a7820a', '5e3c663198']


def test_all_routines_maps_to_structured_scope():
    def fake_llm(prompt, system=None, max_tokens=None):
        return '''{
          "mode":"action",
          "route":"time",
          "action":"remove",
          "standalone_request":"cancelar todas as rotinas ativas",
          "references_previous_turn":false,
          "target":{"entity":"routine","scope":"all","reference":"rotinas ativas","ids":[],"filters":{}},
          "confidence":0.99,
          "reason":"ação em lote sobre a categoria rotina"
        }'''

    result = decide('quero zerar essas rotinas e começar do zero', '', fake_llm)
    assert result is not None
    assert result['route'] == 'time'
    assert result['target']['entity'] == 'routine'
    assert result['target']['scope'] == 'all'
