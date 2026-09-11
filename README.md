# Hermes Local Stack

Distribuição de migração para uma instalação **existente** do NousResearch Hermes Agent rodar como um assistente autônomo local na VPS, sem OmniRoute/OpenRouter/outro provider externo no caminho de inferência.

> Este projeto atua somente sobre o Hermes Agent da VPS. Não altera Freud, `hermes-front` ou `hermes-back`.

## Arquitetura

```text
                       HERMES AGENT
            chat / gateway / tools / cron / agents
                              |
                              v
                  127.0.0.1:8088/v1
                              |
                              v
                 hermes-local-llm.service
                         llama.cpp
                              |
                              v
                Qwen3-4B Q4_K_M (GGUF)

             +-----------------------------+
             | memoria nativa do Hermes    |
             | ~/.hermes/memories          |
             +-----------------------------+
                              |
                              +-- knowledge vault
                                  ~/.hermes/vault
                                  Obsidian-compatible
```

O runtime do modelo continua sendo um processo separado por estabilidade, mas ele é instalado, configurado, iniciado, monitorado e atualizado pela própria stack do Hermes. Não é necessário manter Ollama, OmniRoute ou um servidor de IA separado.

## Por que existe um patch do Hermes

O Hermes upstream possui um piso rígido de 64.000 tokens de contexto para sessões, trocas de modelo e cron. Isso é pesado para modelos locais pequenos e para VPSs sem GPU.

Nossa distribuição mantém o upstream intacto e aplica um patch reaplicável que troca o piso rígido por:

```text
HERMES_MIN_CONTEXT_LENGTH=16384
```

O modelo padrão roda com 32.768 tokens de contexto. Isso permite usar uma IA local menor e compensar a janela reduzida com compressão antecipada e memória persistente.

## Modelo padrão

- Qwen3-4B
- GGUF Q4_K_M
- ~2.5 GB em disco
- contexto nativo: 32.768 tokens
- runtime: llama.cpp
- 1 geração simultânea
- endpoint privado em loopback: `127.0.0.1:8088`
- tool/function calling via `llama-server --jinja`

O modelo pode ser trocado por variáveis `HERMES_LOCAL_MODEL_*` sem mudar o código do Hermes.

## Instalação na VPS existente

Nunca rode o instalador completo como root. Rode como o mesmo usuário que executa o Hermes (`carlos` na VPS atual).

```bash
cd ~/hermes-local-only
git pull

bash ./inspect.sh
bash ./install-full.sh
bash ./verify.sh
```

> Execute os scripts com `bash` em vez de alterar o bit executável com `chmod +x`. Isso mantém o working tree limpo e evita conflitos futuros no `git pull`.

`install-full.sh` usa `sudo` somente se precisar instalar `build-essential`, `cmake`, `git`, `curl` ou certificados do sistema.

## O que `install-full.sh` faz

1. Faz backup de `config.yaml`, `.env`, `auth.json`, cron, SOUL e do arquivo-fonte que receberá o patch.
2. Aplica o patch reaplicável de contexto mínimo.
3. Compila `llama.cpp` dentro de `~/.hermes/local-runtime/`.
4. Baixa o GGUF para `~/.hermes/models/` e valida SHA-256.
5. Cria e inicia `hermes-local-llm.service` como serviço systemd do usuário.
6. Configura `model.provider=custom` e `model.base_url=http://127.0.0.1:8088/v1`.
7. Remove fallback de inferência externo.
8. Move os defaults de cron e delegation para o mesmo modelo local.
9. Migra pins explícitos das rotinas antigas usando `hermes cron edit`, preservando ID, prompt, agenda e estado.
10. Serializa subagentes (`delegation.max_concurrent_children=1`) para não explodir RAM.
11. Ajusta timeouts para CPU local lenta.
12. Configura compressão para começar antes da janela de 32k lotar.
13. Cria o vault `~/.hermes/vault` e define `OBSIDIAN_VAULT_PATH`.
14. Instala a skill `hermes-local-memory` em `~/.hermes/skills/`.
15. Faz o gateway depender do runtime local e executa smoke tests.

## Memória + Obsidian

O Hermes mantém sua memória nativa em `~/.hermes/memories` e as sessões em SQLite. Essa camada continua ativa.

O vault adiciona uma segunda camada, legível por humanos e compatível com Obsidian:

```text
~/.hermes/vault/
├── 00-Inbox/
├── 10-Memory/
├── 20-Projects/
├── 30-Routines/
├── 40-Knowledge/
├── 50-Decisions/
├── 60-Daily/
├── 70-References/
├── 90-Archive/
└── Templates/
```

A skill oficial `obsidian` do Hermes usa `OBSIDIAN_VAULT_PATH`; a skill adicional `hermes-local-memory` define como transformar conversas, decisões, projetos e rotinas em conhecimento durável sem despejar chats inteiros nem segredos no vault.

Não é necessário instalar a interface gráfica do Obsidian na VPS. O diretório é um vault Markdown normal e pode ser aberto/sincronizado com Obsidian em outro computador posteriormente.

## Atualizações do Hermes sem conflito

Use:

```bash
cd ~/hermes-local-only
git pull
bash ./update-local.sh
```

O fluxo é:

```text
backup
  -> hermes update
  -> reaplica patch local pequeno
  -> mantém config/state/memories/vault
  -> reinicia runtime local
  -> reinicia gateway
  -> verify.sh
```

Assim não mantemos milhares de commits divergentes do upstream.

## Diagnóstico

```bash
bash ./inspect.sh
bash ./verify.sh

systemctl --user status hermes-local-llm.service
journalctl --user -u hermes-local-llm.service -f

systemctl --user status hermes-gateway.service
journalctl --user -u hermes-gateway.service -f
```

## Rollback

Cada migração completa cria um snapshot em:

```text
~/.hermes/backups/full-local-only-YYYYMMDD-HHMMSS/
```

Para restaurar o último estado:

```bash
bash ./rollback.sh
```

O rollback restaura configuração, cron e o fonte original do Hermes e desativa o runtime local. O modelo e o vault permanecem em disco para não apagar dados desnecessariamente.

## Segurança

- O endpoint do LLM escuta apenas em `127.0.0.1`.
- Nenhuma API key é necessária para inferência local.
- Credenciais já existentes não são apagadas porque Telegram, voz, web ou outras ferramentas podem precisar delas.
- Nenhum token, senha, prompt privado de cron ou conteúdo do vault é versionado neste repositório.
- O vault não deve armazenar senhas, tokens, private keys ou outras credenciais.

## Scripts antigos

`install.sh` permanece temporariamente no repositório por compatibilidade com a primeira abordagem baseada em endpoint local já existente. Para a arquitetura completa, use **`install-full.sh`**.
