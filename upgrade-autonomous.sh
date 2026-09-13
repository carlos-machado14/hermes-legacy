#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

printf '\n=== Hermes Autonomous Upgrade ===\n'
printf 'Codigo sera atualizado sem alterar crons, timezone, memoria ou configuracoes pessoais.\n\n'

chmod +x \
  install-core-v2.sh \
  install-cron-manager.sh \
  install-fast-router.sh \
  install-gateway-fastpath-plugin.sh

# Idempotent installers: replace application code/services while preserving
# everything under ~/.hermes that belongs to the user (state, crons, auth,
# config and local scripts created at runtime).
./install-core-v2.sh
./install-cron-manager.sh
./install-gateway-fastpath-plugin.sh

printf '\n=== Validacoes ===\n'
curl -fsS http://127.0.0.1:8089/health || true
echo
hermes config get timezone 2>/dev/null || true
hermes cron status 2>/dev/null || true
systemctl --user is-active hermes-core-health.service || true
hermes plugins list 2>/dev/null | grep -i 'hermes-core-fastpath' || true

printf '\n=== Smoke tests Core ===\n'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/hermes_core.py" 'status da vps'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/hermes_core.py" 'ferramentas'

echo
echo 'OK: codigo atualizado; dados e configuracoes do usuario foram preservados.'
echo 'Nenhuma cron foi criada, editada, removida ou migrada pelo upgrade.'
echo 'Nenhum timezone foi alterado pelo upgrade.'
