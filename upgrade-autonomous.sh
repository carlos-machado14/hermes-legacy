#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

printf '\n=== Hermes Core v3.4 Autonomous Goal Execution Upgrade ===\n'
printf 'Codigo sera atualizado sem alterar crons, timezone, memoria, projetos, objetivos, tarefas ou configuracoes pessoais.\n\n'

chmod +x install-core-v2.sh install-cron-manager.sh install-fast-router.sh install-gateway-fastpath-plugin.sh

./install-core-v2.sh
./install-cron-manager.sh
./install-fast-router.sh
./install-gateway-fastpath-plugin.sh

printf '\n=== Validacoes ===\n'
printf 'Fast Router: '; curl -fsS http://127.0.0.1:8089/health || true; echo
printf 'Core API: '; curl -fsS http://127.0.0.1:8090/health || true; echo
printf 'Timezone: '; hermes config get timezone 2>/dev/null || true
hermes cron status 2>/dev/null || true
printf 'Health service: '; systemctl --user is-active hermes-core-health.service || true
printf 'Watcher service: '; systemctl --user is-active hermes-core-watchers.service || true
printf 'API service: '; systemctl --user is-active hermes-core-api.service || true
printf 'Autonomous service: '; systemctl --user is-active hermes-core-autonomous.service || true
hermes plugins list 2>/dev/null | grep -i 'hermes-core-fastpath' || true

printf '\n=== Smoke tests Core v3.4 ===\n'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/hermes_core.py" 'status da vps'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/hermes_core.py" 'status da autonomia'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/hermes_core.py" 'o que voce pode fazer sozinho'

echo
echo 'OK: Hermes Core v3.4 atualizado; dados e configuracoes do usuario foram preservados.'
echo 'Novidades: fila de acoes, execucao autonoma de baixo risco, aprovacao para efeitos externos e ciclos por objetivos.'
echo 'Nenhuma cron, timezone, credencial, memoria, projeto, objetivo ou tarefa do usuario foi criado/editado/removido pelo upgrade.'
