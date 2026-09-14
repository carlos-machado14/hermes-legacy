# Hermes v4.8 — FastPath, SLA e observabilidade

Esta versão mantém o Qwen local pequeno como caminho padrão e só aumenta contexto/tempo quando o pedido exige.

## Fluxo

```text
Telegram / Gateway
  -> hermes-core-fastpath
  -> classificação de complexidade
  -> Core determinístico / memória seletiva / LLM
  -> resposta agendada no MESMO event loop do Gateway
```

O FastPath não cria mais um event loop próprio para responder ao Telegram. Isso evita o problema `RuntimeError('Event loop is closed')` causado por adapters assíncronos reutilizados fora do loop original.

## SLA por complexidade

| Tier | Uso | Timeout do FastPath | Saída padrão |
| --- | --- | ---: | ---: |
| `fast` | resposta literal / health probes | 15s | 120 tokens |
| `normal` | conversa comum | 45s | 280 tokens |
| `hard` | análise/arquitetura/diagnóstico | 120s | 700 tokens |
| `mission` | trabalho durável explícito | 300s | 900 tokens |

Esses limites são limites de segurança, não metas de latência. A meta operacional é manter perguntas simples em poucos segundos.

## Contexto seletivo

Perguntas comuns não recebem todo o perfil, memória e histórico. O Core adiciona contexto somente quando a mensagem é pessoal, depende de conversa anterior ou é complexa.

Isso evita prompts de milhares de tokens para perguntas pequenas.

## Modelo padrão e escalonamento opcional

O modelo local configurado em `~/.hermes/core-v2/config.yaml` continua sendo o padrão. Para usar um modelo OpenAI-compatible apenas em pedidos `hard`/`mission`, configure no ambiente do processo:

```bash
HERMES_HARD_BASE_URL=https://seu-endpoint/v1
HERMES_HARD_MODEL=nome-do-modelo
HERMES_HARD_API_KEY=opcional
```

Sem `HERMES_HARD_BASE_URL` + `HERMES_HARD_MODEL`, **nenhuma chamada remota é feita** e tudo continua local.

## Cancelamento

Durante uma execução longa, o usuário pode mandar:

```text
pare
cancela
interrompa
esquece isso
```

O FastPath invalida a fila daquela conversa, encerra o subprocesso ativo e suprime a resposta antiga.

Também aceita substituição direta:

```text
esquece isso e me fale sobre Roma
```

## Trace ID e métricas

Cada mensagem recebe um `trace_id` que aparece nos logs do Gateway e é repassado ao Core.

Eventos do Core ficam em:

```bash
~/.hermes/core-v2/logs/perf.jsonl
```

Relatório agregado:

```bash
./performance-report.sh
```

Logs do FastPath:

```bash
journalctl --user -u hermes-gateway.service -f | grep -i fastpath
```

## Regressão

Contratos rápidos:

```bash
./run-regression-tests.sh
```

Incluindo modelo local + Core instalado + Plugin Doctor:

```bash
./run-regression-tests.sh --live
```

## Upgrade completo

Depois do `git pull`:

```bash
chmod +x upgrade-hermes-v4.8.sh
./upgrade-hermes-v4.8.sh
```

O script atualiza Core, FastPath, reinicia o Gateway e roda os testes.
