#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

printf '\n=== Hermes Core v3.6 Memory Vault Upgrade ===\n'
printf 'Codigo sera atualizado sem alterar crons, timezone, memoria pessoal, projetos, objetivos, tarefas ou configuracoes pessoais.\n\n'

chmod +x install-core-v2.sh install-conversation-layer.sh install-cron-manager.sh install-fast-router.sh install-gateway-fastpath-plugin.sh

./install-core-v2.sh
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
printf 'Health service: '; systemctl --user is-active hermes-core-health.service || true
printf 'Watcher service: '; systemctl --user is-active hermes-core-watchers.service || true
printf 'API service: '; systemctl --user is-active hermes-core-api.service || true
printf 'Autonomous service: '; systemctl --user is-active hermes-core-autonomous.service || true
hermes plugins list --plain 2>/dev/null | grep -i 'hermes-core-fastpath' || true

printf '\n=== Smoke tests v3.6 ===\n'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/core_entry.py" 'status da memoria'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/core_entry.py" 'o que devo fazer hoje?'

echo
echo 'OK: Memory Vault + camada conversacional instalados; contexto e estado pessoal preservados.'
echo 'Novidades: Markdown estilo Obsidian, indice SQLite leve, recuperacao seletiva e memoria curta de conversa.'
echo 'Nenhuma cron, timezone, credencial, projeto, objetivo, tarefa ou lead do usuario foi removido pelo upgrade.'
