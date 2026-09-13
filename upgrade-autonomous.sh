#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

printf '\n=== Hermes Autonomous Upgrade ===\n'
chmod +x install-core-v2.sh install-cron-manager.sh install-fast-router.sh install-gateway-fastpath-plugin.sh set-brazil-timezone.sh migrate-crons-local.sh

./install-core-v2.sh
./install-cron-manager.sh
./set-brazil-timezone.sh
./migrate-crons-local.sh
./install-gateway-fastpath-plugin.sh

printf '\n=== Validacoes ===\n'
curl -fsS http://127.0.0.1:8089/health || true
echo
hermes config get timezone || true
hermes cron status || true
systemctl --user is-active hermes-core-health.service || true
hermes plugins list 2>/dev/null | grep -i 'hermes-core-fastpath' || true

printf '\n=== Smoke tests Core v2.1 ===\n'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/hermes_core.py" 'status da vps'
"$HOME/.hermes/core-v2/venv/bin/python" "$HOME/.hermes/core-v2/hermes_core.py" 'ferramentas'

echo
echo 'OK: Hermes Core v2.1 + Fast Router v9 + gateway pre-compression fastpath + Cron Manager + recovery instalados.'
echo 'Teste pelo Telegram: status da vps'
echo 'Teste pelo Telegram: corrija tudo'
echo 'Teste pelo Telegram: o que voce corrigiu?'
