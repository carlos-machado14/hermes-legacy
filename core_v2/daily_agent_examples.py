from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

# Few-shot corpus for the lightweight local semantic agent. These are examples,
# never exact commands or phrase routes: selection only retrieves similar examples
# to teach the model the expected semantic JSON contract.
EXAMPLES: list[dict[str, Any]] = [
    # Read agenda / schedule
    {'u':'o que tenho hoje','o':{'mode':'query','route':'time','action':'list','entity':'day','scope':'filtered'}},
    {'u':'como está minha agenda de hoje','o':{'mode':'query','route':'time','action':'list','entity':'day','scope':'filtered'}},
    {'u':'tem alguma coisa pra amanhã','o':{'mode':'query','route':'time','action':'list','entity':'day','scope':'filtered'}},
    {'u':'qual minha agenda sexta','o':{'mode':'query','route':'time','action':'list','entity':'day','scope':'filtered'}},
    {'u':'agenda do dia 25/09','o':{'mode':'query','route':'time','action':'list','entity':'day','scope':'filtered'}},
    {'u':'o que eu tenho semana que vem','o':{'mode':'query','route':'time','action':'list','entity':'day','scope':'filtered'}},
    {'u':'me mostra meus compromissos deste mês','o':{'mode':'query','route':'time','action':'list','entity':'commitment','scope':'filtered'}},
    {'u':'tenho algo às 17h','o':{'mode':'query','route':'time','action':'list','entity':'schedule','scope':'filtered'}},
    {'u':'quais rotinas estão ativas','o':{'mode':'query','route':'automation','action':'list','entity':'routine','scope':'all'}},
    {'u':'quais lembretes eu tenho','o':{'mode':'query','route':'time','action':'list','entity':'reminder','scope':'all'}},
    {'u':'meus alertas de amanhã','o':{'mode':'query','route':'time','action':'list','entity':'alert','scope':'filtered'}},

    # Create reminder / event / routine
    {'u':'me lembra amanhã às 9 de pagar a conta','o':{'mode':'action','route':'time','action':'create','entity':'reminder','scope':'single'}},
    {'u':'amanhã 10h me avisa de revisar o projeto','o':{'mode':'action','route':'time','action':'create','entity':'reminder','scope':'single'}},
    {'u':'coloca na agenda dentista terça às 14','o':{'mode':'action','route':'time','action':'create','entity':'event','scope':'single'}},
    {'u':'marca reunião com o João sexta 15h','o':{'mode':'action','route':'time','action':'create','entity':'event','scope':'single'}},
    {'u':'todo dia às 8 me lembra de tomar remédio','o':{'mode':'action','route':'automation','action':'create','entity':'routine','scope':'single'}},
    {'u':'de segunda a sexta às 18 me avise para encerrar o trabalho','o':{'mode':'action','route':'automation','action':'create','entity':'routine','scope':'single'}},
    {'u':'a cada 30 minutos entre 8 e 17 me lembra de beber água','o':{'mode':'action','route':'automation','action':'create','entity':'routine','scope':'single'}},
    {'u':'me alerta daqui 20 minutos','o':{'mode':'action','route':'time','action':'create','entity':'alert','scope':'single'}},
    {'u':'me lembra quando eu chegar em casa de ligar pra minha mãe','o':{'mode':'action','route':'time','action':'create','entity':'reminder','scope':'single'}},

    # Remove / cancel
    {'u':'cancela esse lembrete','o':{'mode':'followup','route':'time','action':'remove','entity':'reminder','scope':'single'}},
    {'u':'apaga o lembrete de amanhã às 10','o':{'mode':'action','route':'time','action':'remove','entity':'reminder','scope':'filtered'}},
    {'u':'cancele todos os meus lembretes de hoje','o':{'mode':'action','route':'time','action':'remove','entity':'reminder','scope':'filtered'}},
    {'u':'remove todas as rotinas de hidratação','o':{'mode':'action','route':'automation','action':'remove','entity':'routine','scope':'filtered'}},
    {'u':'pode excluir todas elas','o':{'mode':'followup','route':'automation','action':'remove','entity':'unknown','scope':'selection'}},
    {'u':'tira isso da agenda','o':{'mode':'followup','route':'time','action':'remove','entity':'event','scope':'single'}},

    # Pause / resume / run
    {'u':'pausa minha rotina de água por enquanto','o':{'mode':'action','route':'automation','action':'pause','entity':'routine','scope':'filtered'}},
    {'u':'desativa essa rotina','o':{'mode':'followup','route':'automation','action':'pause','entity':'routine','scope':'single'}},
    {'u':'volta a ativar meu lembrete diário','o':{'mode':'action','route':'automation','action':'resume','entity':'routine','scope':'filtered'}},
    {'u':'reativa ela','o':{'mode':'followup','route':'automation','action':'resume','entity':'routine','scope':'single'}},
    {'u':'roda essa rotina agora','o':{'mode':'followup','route':'automation','action':'run','entity':'routine','scope':'single'}},

    # Reschedule / update
    {'u':'muda meu dentista para 16h','o':{'mode':'action','route':'time','action':'reschedule','entity':'event','scope':'filtered'}},
    {'u':'joga isso pra amanhã','o':{'mode':'followup','route':'time','action':'reschedule','entity':'unknown','scope':'single'}},
    {'u':'passa a reunião de sexta para segunda de manhã','o':{'mode':'action','route':'time','action':'reschedule','entity':'event','scope':'filtered'}},
    {'u':'troca o horário do lembrete para 18h','o':{'mode':'action','route':'time','action':'update','entity':'reminder','scope':'filtered'}},
    {'u':'em vez de 30 em 30 deixa a cada hora','o':{'mode':'followup','route':'automation','action':'update','entity':'routine','scope':'single'}},

    # Tasks
    {'u':'cria uma tarefa pra revisar o contrato','o':{'mode':'action','route':'task','action':'create','entity':'task','scope':'single'}},
    {'u':'anota que preciso responder o cliente amanhã','o':{'mode':'action','route':'task','action':'create','entity':'task','scope':'single'}},
    {'u':'quais tarefas estão pendentes','o':{'mode':'query','route':'task','action':'list','entity':'task','scope':'all'}},
    {'u':'o que falta fazer hoje','o':{'mode':'query','route':'task','action':'list','entity':'task','scope':'filtered'}},
    {'u':'terminei a coleta dos dados da empresa','o':{'mode':'action','route':'task','action':'complete','entity':'task','scope':'filtered'}},
    {'u':'marca essa como concluída','o':{'mode':'followup','route':'task','action':'complete','entity':'task','scope':'single'}},
    {'u':'não consegui terminar isso hoje','o':{'mode':'followup','route':'task','action':'reschedule','entity':'task','scope':'single'}},
    {'u':'remove essa tarefa','o':{'mode':'followup','route':'task','action':'remove','entity':'task','scope':'single'}},
    {'u':'essa tarefa agora é prioridade','o':{'mode':'followup','route':'task','action':'update','entity':'task','scope':'single'}},

    # Priority / planning / assistant reasoning (delegate to larger model)
    {'u':'hoje estou enrolado o que é mais importante','o':{'mode':'query','route':'assistant','action':'answer','entity':'day','scope':'filtered'}},
    {'u':'organiza meu dia','o':{'mode':'query','route':'assistant','action':'answer','entity':'day','scope':'filtered'}},
    {'u':'me ajuda a decidir o que faço primeiro','o':{'mode':'query','route':'assistant','action':'answer','entity':'task','scope':'all'}},
    {'u':'resume meu dia pra mim','o':{'mode':'query','route':'assistant','action':'answer','entity':'day','scope':'filtered'}},
    {'u':'o que está atrasado','o':{'mode':'query','route':'task','action':'status','entity':'task','scope':'filtered'}},

    # Natural conversation / general knowledge -> larger model
    {'u':'bom dia','o':{'mode':'chat','route':'assistant','action':'answer','entity':'unknown','scope':'unknown'}},
    {'u':'valeu','o':{'mode':'chat','route':'assistant','action':'answer','entity':'unknown','scope':'unknown'}},
    {'u':'me explica como funciona bcrypt','o':{'mode':'query','route':'assistant','action':'answer','entity':'unknown','scope':'unknown'}},
    {'u':'como faço isso em flutter','o':{'mode':'query','route':'developer','action':'answer','entity':'unknown','scope':'unknown'}},
    {'u':'por que meu docker está dando erro','o':{'mode':'query','route':'devops','action':'answer','entity':'unknown','scope':'unknown'}},
    {'u':'procura na internet as notícias de hoje','o':{'mode':'query','route':'research','action':'search','entity':'unknown','scope':'unknown'}},
    {'u':'busca o preço mais barato dessa passagem','o':{'mode':'query','route':'research','action':'search','entity':'unknown','scope':'unknown'}},
    {'u':'lembra do que conversamos sobre o projeto','o':{'mode':'query','route':'memory','action':'search','entity':'unknown','scope':'unknown'}},

    # Context and pronouns
    {'u':'e amanhã','o':{'mode':'followup','route':'time','action':'list','entity':'day','scope':'filtered'}},
    {'u':'e semana que vem','o':{'mode':'followup','route':'time','action':'list','entity':'day','scope':'filtered'}},
    {'u':'e o outro','o':{'mode':'followup','route':'chat','action':'answer','entity':'unknown','scope':'single'}},
    {'u':'esse aí pode apagar','o':{'mode':'followup','route':'chat','action':'answer','entity':'unknown','scope':'single'}},
    {'u':'faz o mesmo com o de sexta','o':{'mode':'followup','route':'chat','action':'answer','entity':'unknown','scope':'filtered'}},
    {'u':'não esse, o anterior','o':{'mode':'followup','route':'chat','action':'answer','entity':'unknown','scope':'single'}},

    # Ambiguity: ask, never guess mutation
    {'u':'muda isso','o':{'mode':'followup','route':'chat','action':'answer','entity':'unknown','scope':'unknown'}},
    {'u':'apaga','o':{'mode':'followup','route':'chat','action':'answer','entity':'unknown','scope':'unknown'}},
    {'u':'me lembra disso depois','o':{'mode':'followup','route':'chat','action':'answer','entity':'reminder','scope':'single'}},
    {'u':'marca pra mais tarde','o':{'mode':'followup','route':'chat','action':'answer','entity':'unknown','scope':'single'}},

    # Negation / question safety
    {'u':'eu tenho algum lembrete que eu deveria cancelar','o':{'mode':'query','route':'time','action':'list','entity':'reminder','scope':'filtered'}},
    {'u':'quais rotinas posso pausar','o':{'mode':'query','route':'automation','action':'list','entity':'routine','scope':'all'}},
    {'u':'você cancelou meu lembrete','o':{'mode':'query','route':'time','action':'status','entity':'reminder','scope':'filtered'}},
    {'u':'não cancele nada hoje','o':{'mode':'chat','route':'assistant','action':'answer','entity':'day','scope':'filtered'}},
    {'u':'não quero mais receber esse alerta','o':{'mode':'action','route':'time','action':'remove','entity':'alert','scope':'single'}},

    # Informal Brazilian Portuguese
    {'u':'me dá um toque 9h','o':{'mode':'action','route':'time','action':'create','entity':'reminder','scope':'single'}},
    {'u':'me chama daqui meia hora','o':{'mode':'action','route':'time','action':'create','entity':'reminder','scope':'single'}},
    {'u':'bota isso pra segunda','o':{'mode':'followup','route':'time','action':'reschedule','entity':'unknown','scope':'single'}},
    {'u':'deixa isso pra depois','o':{'mode':'followup','route':'time','action':'reschedule','entity':'unknown','scope':'single'}},
    {'u':'oq tem pra hj','o':{'mode':'query','route':'time','action':'list','entity':'day','scope':'filtered'}},
    {'u':'tem algo p amanhã','o':{'mode':'query','route':'time','action':'list','entity':'day','scope':'filtered'}},
    {'u':'manda minhas tarefas','o':{'mode':'query','route':'task','action':'list','entity':'task','scope':'all'}},
    {'u':'quero parar aquele aviso das 17','o':{'mode':'action','route':'time','action':'remove','entity':'reminder','scope':'filtered'}},
]


def _norm(text: str) -> set[str]:
    value = unicodedata.normalize('NFKD', str(text or '').casefold())
    value = ''.join(ch for ch in value if not unicodedata.combining(ch))
    return {p for p in re.findall(r'[a-z0-9]+', value) if len(p) > 1}


def select_examples(text: str, limit: int = 7) -> str:
    query = _norm(text)
    ranked: list[tuple[float, int, dict[str, Any]]] = []
    for idx, item in enumerate(EXAMPLES):
        tokens = _norm(item['u'])
        overlap = len(query & tokens)
        union = max(1, len(query | tokens))
        score = (overlap / union) + (0.04 * overlap)
        ranked.append((score, -idx, item))
    ranked.sort(reverse=True, key=lambda row: (row[0], row[1]))
    chosen = [item for score, _idx, item in ranked[:max(3, min(limit, 10))] if score > 0]
    if len(chosen) < 3:
        chosen = [row[2] for row in ranked[:3]]
    lines = []
    for item in chosen:
        lines.append(json.dumps({'u': item['u'], **item['o']}, ensure_ascii=False, separators=(',', ':')))
    return '\n'.join(lines)
