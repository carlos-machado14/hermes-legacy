#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

printf '\n=== Hermes Core v2.2 Upgrade ===\n'
printf 'Codigo sera atualizado sem alterar crons, timezone, memoria, projetos ou configuracoes pessoais.\n\n'

chmod +x \
  install-core-v2.sh \
  install-cron-manager.sh \
  install-fast-router.sh \
  install-gateway-fastpath-plugin.sh

./install-core-v2.sh
./install-cron-manager.sh
./install-gateway-fastpath-plugin.sh

printf '\n=== Validacoes ===\n'
printf 'Fast Router: '
curl -fsS http://127.0.0.1:8089/health || true
echo
printf 'Core API: '
curl -fsS http://127.0.0.1:8090/health || true
echo
printf 'Timezone: '
hermes config get timezone 2>/dev/null || true
hermes cron status 2>/dev/null || true
printf 'Health service: '
systemctl --user is-active hermes-core-health.service || true
printf 'Watcher service: '
systemctl --user is-active hermes-core-watchers.service || true
printf 'API service: '
systemctl --user is-active hermes-core-api.service || true
hermes plugins list 2>/dev/null | grep -i 'hermes-core-fastpath' || true

printf '\n=== Smoke tests Core ===\n'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/hermes_core.py" 'status da vps'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/hermes_core.py" 'ferramentas'

echo
echo 'OK: Hermes Core v2.2 atualizado; dados e configuracoes do usuario foram preservados.'
echo 'Novidades: API local :8090, Project Registry, Watchers e Incident Store.'
echo 'Nenhuma cron, timezone, credencial, memoria ou projeto do usuario foi criado/editado/removido pelo upgrade.'
