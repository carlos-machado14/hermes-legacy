#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

printf '\n=== Hermes Core v4 Autonomous Execution Runtime Upgrade ===\n'
printf 'Codigo sera atualizado sem alterar crons, timezone, memoria pessoal, projetos, objetivos, tarefas ou configuracoes pessoais.\n\n'

chmod +x install-core-v2.sh install-v4-runtime.sh install-conversation-layer.sh install-cron-manager.sh install-fast-router.sh install-gateway-fastpath-plugin.sh

./install-core-v2.sh
./install-v4-runtime.sh
./install-conversation-layer.sh
./install-cron-manager.sh
./install-fast-router.sh
./install-gateway-fastpath-plugin.sh

printf '\n=== Validacoes ===\n'
printf 'Fast Router: '; curl -fsS http://127.0.0.1:8089/health || true; echo
printf 'Core API: '; curl -fsS http://127.0.0.1:8090/health || true; echo
printf 'Conversation entry: '; test -x "$HOME/.hermes/core-v2/core_entry.py" && echo active || echo missing
printf 'Memory Vault: '; test -d "$HOME/.hermes/memory" && echo active || echo missing
printf 'Memory index: '; test -f "$HOME/.hermes/core-v2/state/memory_index.sqlite3" && echo active || echo missing
printf 'Durable jobs DB: '; test -f "$HOME/.hermes/core-v2/state/jobs.sqlite3" && echo active || echo ready-on-first-use
printf 'Health service: '; systemctl --user is-active hermes-core-health.service || true
printf 'Watcher service: '; systemctl --user is-active hermes-core-watchers.service || true
printf 'API service: '; systemctl --user is-active hermes-core-api.service || true
printf 'Autonomous service: '; systemctl --user is-active hermes-core-autonomous.service || true
printf 'Durable worker: '; systemctl --user is-active hermes-core-durable-worker.service || true
hermes plugins list --plain 2>/dev/null | grep -i 'hermes-core-fastpath' || true

printf '\n=== Smoke tests v4 ===\n'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/core_entry.py" 'status da memoria'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/core_entry.py" 'meus jobs'

echo
echo 'OK: Hermes v4 Durable Mission Runtime + Memory Vault + camada conversacional instalados.'
echo 'Novidades: jobs persistentes, checkpoints, retomada apos restart, planner, executor e validator.'
echo 'Nenhuma cron, timezone, credencial, projeto, objetivo, tarefa ou lead do usuario foi removido pelo upgrade.'
