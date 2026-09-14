#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

printf '\n=== Hermes Core v4.5 General Assistant + Optional Connected Bridge Upgrade ===\n'
printf 'Codigo sera atualizado sem alterar crons, timezone, memoria pessoal, projetos, objetivos, tarefas ou configuracoes pessoais.\n'
printf 'A integracao com Freud e OPCIONAL e nao e necessaria para o Hermes funcionar.\n\n'

chmod +x install-core-v2.sh install-v4-runtime.sh install-web-research.sh install-universal-agent.sh install-conversation-layer.sh install-cron-manager.sh install-fast-router.sh install-gateway-fastpath-plugin.sh

./install-core-v2.sh
./install-v4-runtime.sh
./install-web-research.sh
./install-universal-agent.sh
./install-conversation-layer.sh
./install-cron-manager.sh
./install-fast-router.sh
./install-gateway-fastpath-plugin.sh

printf '\n=== Aplicando correcoes de roteamento atual e linguagem natural ===\n'
"$HOME/.hermes/core-v2/venv/bin/python" "$ROOT/patches/apply_realtime_and_natural_cron_v2.py"

printf '\n=== Aplicando confirmacao conversacional de rotinas ===\n'
"$HOME/.hermes/core-v2/venv/bin/python" "$ROOT/patches/apply_routine_confirmation_v1.py"

printf '\n=== Reparando ordem de execucao do cron manager ===\n'
"$HOME/.hermes/core-v2/venv/bin/python" "$ROOT/patches/repair_routine_confirmation_guard.py"

printf '\n=== Aplicando guarda geral de intencao ===\n'
"$HOME/.hermes/core-v2/venv/bin/python" "$ROOT/patches/apply_intent_guard_v1.py"

printf '\n=== Validando confirmacao de rotinas ===\n'
"$HOME/.hermes/core-v2/venv/bin/python" "$ROOT/patches/verify_routine_confirmation.py"

printf '\n=== Validacoes ===\n'
printf 'Fast Router: '; curl -fsS http://127.0.0.1:8089/health || true; echo
printf 'Core API: '; curl -fsS http://127.0.0.1:8090/health || true; echo
printf 'SearXNG: '; curl -fsS 'http://127.0.0.1:8087/search?q=hermes&format=json' >/dev/null 2>&1 && echo active || echo unavailable
printf 'Conversation entry: '; test -x "$HOME/.hermes/core-v2/core_entry.py" && echo active || echo missing
printf 'Optional Freud bridge code: '; test -f "$HOME/.hermes/core-v2/freud_broker_client.py" && echo available || echo missing
printf 'Memory Vault: '; test -d "$HOME/.hermes/memory" && echo active || echo missing
printf 'Memory index: '; test -f "$HOME/.hermes/core-v2/state/memory_index.sqlite3" && echo active || echo missing
printf 'Durable jobs DB: '; test -f "$HOME/.hermes/core-v2/state/jobs.sqlite3" && echo active || echo ready-on-first-use
printf 'Audit trail: '; test -f "$HOME/.hermes/core-v2/state/audit.jsonl" && echo active || echo ready-on-first-use
printf 'Health service: '; systemctl --user is-active hermes-core-health.service || true
printf 'Watcher service: '; systemctl --user is-active hermes-core-watchers.service || true
printf 'API service: '; systemctl --user is-active hermes-core-api.service || true
printf 'OpenAI bridge: '; systemctl --user is-active hermes-openai-bridge.service || true
printf 'Autonomous service: '; systemctl --user is-active hermes-core-autonomous.service || true
printf 'Durable worker: '; systemctl --user is-active hermes-core-durable-worker.service || true
hermes plugins list --plain 2>/dev/null | grep -i 'hermes-core-fastpath' || true

printf '\n=== Smoke tests v4.5 ===\n'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/core_entry.py" 'meu dia'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/core_entry.py" 'recursos'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/core_entry.py" 'meus jobs'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/core_entry.py" 'status web'

echo
echo 'OK: Hermes v4.5 instalado em modo independente.'
echo 'Hermes continua funcionando sozinho com memoria, web, browser, missoes, agentes e automacoes.'
echo 'Ponte Hermes <-> Freud existe apenas como capacidade opcional futura e fica inativa sem configuracao explicita.'
echo 'Nenhuma conexao entre VPSs e exigida.'
echo 'Nenhuma cron, timezone, credencial, projeto, objetivo, tarefa ou dado pessoal foi removido pelo upgrade.'
