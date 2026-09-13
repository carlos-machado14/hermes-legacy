#!/usr/bin/env bash
set -euo pipefail

HERMES_BIN="${HERMES_BIN:-$(command -v hermes)}"
SCRIPTS="$HOME/.hermes/scripts"
BACKUP_DIR="$HOME/.hermes/backups/core-v2-crons-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

if [ -z "${HERMES_BIN:-}" ]; then
  echo "hermes CLI nao encontrado" >&2
  exit 1
fi

mkdir -p "$SCRIPTS"

# Snapshot visivel antes de alterar. O Hermes CLI atual nao expoe o prompt completo,
# mas isso preserva os metadados/estado para auditoria.
"$HERMES_BIN" cron list --all > "$BACKUP_DIR/cron-list-before.txt" 2>&1 || true

edit_job() {
  local name="$1"
  local script="$2"
  echo "[cron] Migrando: $name"
  "$HERMES_BIN" cron edit "$name" \
    --script "$script" \
    --no-agent \
    --clear-skills \
    --deliver telegram
}

edit_job "AI Daily Brief" "$SCRIPTS/ai-daily-brief.sh"
edit_job "Marketing & Leads Brief" "$SCRIPTS/marketing-leads-brief.sh"
edit_job "Daily Product Opportunity Brief" "$SCRIPTS/product-opportunity-brief.sh"
edit_job "Financial Brief - Assinaturas" "$SCRIPTS/financial-subscriptions-brief.sh"

"$HERMES_BIN" cron list --all > "$BACKUP_DIR/cron-list-after.txt" 2>&1 || true

echo
echo "Migracao concluida. Backup: $BACKUP_DIR"
echo "Teste imediato:"
echo "  hermes cron run 'AI Daily Brief'"
echo "  hermes cron tick"
