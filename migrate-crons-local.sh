#!/usr/bin/env bash
set -euo pipefail

HERMES_BIN="${HERMES_BIN:-$(command -v hermes)}"
BACKUP_DIR="$HOME/.hermes/backups/core-v2-crons-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

if [ -z "${HERMES_BIN:-}" ]; then
  echo "hermes CLI nao encontrado" >&2
  exit 1
fi

# O Hermes exige que --script seja relativo a ~/.hermes/scripts/.
# Editar tambem o schedule força o scheduler a recalcular next_run_at
# usando o timezone atual do gateway (America/Sao_Paulo).
edit_job() {
  local name="$1"
  local script_name="$2"
  local schedule="$3"
  echo "[cron] Migrando: $name -> $script_name @ $schedule"
  "$HERMES_BIN" cron edit "$name" \
    --schedule "$schedule" \
    --script "$script_name" \
    --no-agent \
    --clear-skills \
    --deliver telegram
}

"$HERMES_BIN" cron list --all > "$BACKUP_DIR/cron-list-before.txt" 2>&1 || true

# Horarios em Brasilia (America/Sao_Paulo), propositalmente separados
# para evitar disputa de CPU/rede entre coletores.
edit_job "Financial Brief - Assinaturas" "financial-subscriptions-brief.sh" "0 9 * * *"
edit_job "AI Daily Brief" "ai-daily-brief.sh" "0 11 * * *"
edit_job "Marketing & Leads Brief" "marketing-leads-brief.sh" "20 11 * * *"
edit_job "Daily Product Opportunity Brief" "product-opportunity-brief.sh" "40 11 * * *"

# Reinicia o gateway para garantir que o scheduler esteja no TZ configurado.
systemctl --user restart hermes-gateway.service 2>/dev/null || true
sleep 2
"$HERMES_BIN" cron tick >/dev/null 2>&1 || true

"$HERMES_BIN" cron list --all > "$BACKUP_DIR/cron-list-after.txt" 2>&1 || true

echo
echo "Migracao concluida. Backup: $BACKUP_DIR"
echo "Horarios (Brasilia):"
echo "  09:00  Financial Brief - Assinaturas"
echo "  11:00  AI Daily Brief"
echo "  11:20  Marketing & Leads Brief"
echo "  11:40  Daily Product Opportunity Brief"
echo
echo "Confira agora:"
echo "  hermes cron list"
