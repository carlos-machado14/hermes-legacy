#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

printf '\n=== Hermes Core Conversational Upgrade ===\n'
printf 'Codigo sera atualizado sem alterar crons, timezone, memoria, projetos, objetivos, tarefas ou configuracoes pessoais.\n\n'

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
printf 'Timezone: '; hermes config get timezone 2>/dev/null || true
hermes cron status 2>/dev/null || true
printf 'Health service: '; systemctl --user is-active hermes-core-health.service || true
printf 'Watcher service: '; systemctl --user is-active hermes-core-watchers.service || true
printf 'API service: '; systemctl --user is-active hermes-core-api.service || true
printf 'Autonomous service: '; systemctl --user is-active hermes-core-autonomous.service || true
hermes plugins list 2>/dev/null | grep -i 'hermes-core-fastpath' || true

printf '\n=== Smoke tests conversacionais ===\n'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/core_entry.py" 'meus objetivos'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/core_entry.py" 'o que devo fazer hoje?'

echo
echo 'OK: camada conversacional instalada; contexto, objetivos e dados do usuario foram preservados.'
echo 'Novidades: memoria curta de conversa, referencias contextuais e fallback LLM enriquecido e mais rapido.'
echo 'Nenhuma cron, timezone, credencial, memoria pessoal, projeto, objetivo ou tarefa do usuario foi removido pelo upgrade.'
