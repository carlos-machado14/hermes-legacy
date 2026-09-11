#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Run rollback.sh as the Hermes user, not root." >&2
  exit 1
fi

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
BACK_ROOT="$HERMES_HOME/backups"
LATEST="${1:-$(find "$BACK_ROOT" -maxdepth 1 -type d \( -name 'full-local-only-*' -o -name 'local-only-*' \) -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n1 | cut -d' ' -f2-)}"
[[ -n "$LATEST" && -d "$LATEST" ]] || { echo "Nenhum backup compatível encontrado em $BACK_ROOT" >&2; exit 1; }

echo "Restaurando: $LATEST"

# Stop the managed model before restoring the previous provider configuration.
systemctl --user stop hermes-gateway.service 2>/dev/null || true
systemctl --user disable --now hermes-local-llm.service 2>/dev/null || true

for rel in config.yaml .env auth.json cron/jobs.json SOUL.md; do
  if [[ -f "$LATEST/$rel" ]]; then
    mkdir -p "$HERMES_HOME/$(dirname "$rel")"
    cp -a "$LATEST/$rel" "$HERMES_HOME/$rel"
    echo "restaurado $rel"
  fi
done

if [[ -f "$LATEST/hermes-source/model_metadata.py" ]]; then
  cp -a "$LATEST/hermes-source/model_metadata.py" "$HERMES_HOME/hermes-agent/agent/model_metadata.py"
  echo 'restaurado hermes-source/model_metadata.py'
fi

DROPIN="$HOME/.config/systemd/user/hermes-gateway.service.d/local-only.conf"
rm -f "$DROPIN"

# Restore previous gateway drop-ins when the backup contains them.
if [[ -d "$LATEST/systemd/hermes-gateway.service.d" ]]; then
  mkdir -p "$HOME/.config/systemd/user/hermes-gateway.service.d"
  cp -a "$LATEST/systemd/hermes-gateway.service.d/." "$HOME/.config/systemd/user/hermes-gateway.service.d/"
fi

systemctl --user daemon-reload
systemctl --user restart hermes-gateway.service 2>/dev/null || {
  command -v hermes >/dev/null 2>&1 && HERMES_HOME="$HERMES_HOME" hermes gateway restart >/dev/null 2>&1 || true
}

echo 'Rollback concluído.'
echo 'O modelo/vault foram mantidos em disco para evitar perda de dados; apenas deixaram de ser usados.'
