# Hermes Core v5.2 — Semantic Agent

## Princípio

O Hermes não deve funcionar como um bot de comandos. A linguagem natural é interpretada uma vez pelo cérebro semântico e convertida para uma intenção estruturada. O executor trabalha sobre essa estrutura e sobre o estado real do Hermes.

## Pipeline

1. Leitura local segura para consultas de estado muito simples.
2. Conversation Brain recebe conversa recente + estado operacional.
3. O Brain produz `route`, `action`, `target`, `scope`, `reference`, `ids` e `filters`.
4. `intent_executor.py` executa diretamente a intenção estruturada para ações internas suportadas.
5. Parsers de texto ficam como fallback ou extratores de dados, nunca como cérebro principal.
6. O resultado é persistido na conversa e no estado operacional.

## Regra importante

Não reescrever uma mensagem e depois tentar descobrir novamente a intenção por regex/parsers. Isso perde contexto e foi a causa de vários erros de cancelamento, seleção e follow-up.

## Comportamento esperado

- "cancele nossos lembretes" -> `time/remove/reminder/all`
- "cancele toda minha agenda" -> `time/remove/schedule/all`
- "tira o do André" após contexto -> `time/remove/<entidade>/single(reference=André)`
- "finalizei isso" após contexto -> `task/complete/selection|single`
- "e amanhã?" -> consulta usando o contexto anterior e o estado local.

O usuário não precisa aprender comandos, IDs ou frases especiais.
