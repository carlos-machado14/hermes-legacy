# Hermes Local-Only

Camada de migração para uma instalação **existente** do NousResearch Hermes Agent rodar com **um único modelo local na VPS**, sem OmniRoute/OpenRouter/outro provider no caminho de inferência.

> Este projeto não é o Freud e não altera `hermes-front`/`hermes-back`. Ele trabalha diretamente sobre o Hermes Agent instalado na VPS.

## Objetivo

```text
Hermes (chat + tools + gateway + cron + subagentes)
                      |
                      v
          http://127.0.0.1:11434/v1
                      |
                      v
                modelo local
```

O instalador não reinstala o Hermes e não recria as rotinas. Ele preserva IDs, agendas, prompts, estado, skills, memória e credenciais de ferramentas.

## Por que migrar as rotinas também

Hermes pode persistir `model` e `model_provider` **por job** em `~/.hermes/cron/jobs.json`. Uma rotina antiga pinada em `OmniRoute NGC / combo-free` continuaria tentando esse provider mesmo após trocar o modelo global. O `install.sh` migra esses pins para `custom / <modelo-local>`.

## Fluxo recomendado na VPS

```bash
git clone https://github.com/carlos-machado14/hermes-local-only.git
cd hermes-local-only
chmod +x *.sh

# 1. Só lê o estado; não altera nada.
./inspect.sh

# 2. Migra a instalação atual e configura Ollama via systemd.
sudo -E ./install.sh

# 3. Confere provider, rotinas e executa uma chamada real pelo Hermes.
./verify.sh
```

Se o repositório já estiver clonado:

```bash
cd hermes-local-only
git pull
sudo -E ./install.sh
./verify.sh
```

## Escolher modelo explicitamente

O instalador usa o primeiro modelo retornado por `http://127.0.0.1:11434/v1/models`. Para fixar outro:

```bash
sudo -E \
  HERMES_LOCAL_MODEL='seu-modelo:tag' \
  HERMES_LOCAL_CONTEXT=65536 \
  ./install.sh
```

Endpoint diferente:

```bash
sudo -E \
  HERMES_LOCAL_MODEL='seu-modelo' \
  HERMES_LOCAL_BASE_URL='http://127.0.0.1:1234/v1' \
  ./install.sh
```

## O que o instalador muda

- `model.provider = custom`
- `model.base_url = http://127.0.0.1:11434/v1`
- `model.default = <modelo local detectado>`
- `model.context_length = 65536` por padrão
- limpa a cadeia de fallback de LLM
- `cron.model_provider = custom`
- `cron.model = <modelo local>`
- migra pins antigos de cada job para `custom/<modelo local>`
- fixa delegation/subagentes no mesmo modelo
- auxiliary `compression`, `vision` e `title_generation` passam a herdar `main`
- Ollama: `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_KEEP_ALIVE=10m`

## O que ele NÃO muda

- Telegram/WhatsApp/GitHub e credenciais de tools
- prompts das rotinas
- horários/agendas
- IDs das rotinas
- skills
- memória
- arquivos de sessão
- código-fonte do Hermes

## Backup e rollback

Cada execução cria um snapshot em:

```text
~/.hermes/backups/local-only-YYYYMMDD-HHMMSS/
```

Inclui `config.yaml`, `.env`, `auth.json` e `cron/jobs.json` quando existirem.

Rollback para o backup mais recente:

```bash
sudo -E ./rollback.sh
```

Ou informe um backup específico:

```bash
sudo -E ./rollback.sh ~/.hermes/backups/local-only-20260911-120000
```

## Segurança

Nenhum token ou configuração privada da VPS é versionado neste repositório. `inspect.sh` mostra somente nomes de variáveis sensíveis existentes no `.env`, nunca seus valores, e não imprime os prompts das rotinas.
