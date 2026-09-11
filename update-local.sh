#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Run update-local.sh as the Hermes user, not root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export HERMES_HOME
HERMES_BIN="${HERMES_BIN:-$(command -v hermes || true)}"
[[ -n "$HERMES_BIN" ]] || { echo 'Hermes CLI not found' >&2; exit 1; }

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$HERMES_HOME/backups/pre-upstream-update-$STAMP"
mkdir -p "$BACKUP"
cp -a "$HERMES_HOME/config.yaml" "$BACKUP/config.yaml" 2>/dev/null || true
cp -a "$HERMES_HOME/.env" "$BACKUP/.env" 2>/dev/null || true
cp -a "$HERMES_HOME/cron/jobs.json" "$BACKUP/jobs.json" 2>/dev/null || true
cp -a "$HERMES_HOME/hermes-agent/agent/model_metadata.py" "$BACKUP/model_metadata.py" 2>/dev/null || true

echo "backup=$BACKUP"
echo 'Stopping gateway for a clean source update...'
systemctl --user stop hermes-gateway.service 2>/dev/null || true

echo 'Updating official Hermes checkout...'
if ! "$HERMES_BIN" update; then
  echo 'Hermes update failed. Restarting previous gateway.' >&2
  systemctl --user start hermes-gateway.service 2>/dev/null || true
  exit 2
fi

echo 'Reapplying local-context compatibility patch...'
python3 "$SCRIPT_DIR/patches/apply_local_context.py"

# Configuration, database, memories and vault live outside the source checkout and are intentionally
# not overwritten by this updater.
systemctl --user daemon-reload
systemctl --user restart hermes-local-llm.service 2>/dev/null || true
for _ in $(seq 1 60); do
  curl -fsS --max-time 2 http://127.0.0.1:8088/v1/models >/dev/null 2>&1 && break
  sleep 2
done
systemctl --user restart hermes-gateway.service 2>/dev/null || "$HERMES_BIN" gateway restart || true

echo 'Running local stack verification...'
bash "$SCRIPT_DIR/verify.sh"
