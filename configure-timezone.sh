#!/usr/bin/env bash
set -Eeuo pipefail

# Usage:
#   ./configure-timezone.sh America/Sao_Paulo
# or:
#   HERMES_TIMEZONE=Europe/Rome ./configure-timezone.sh
# If omitted, keep the machine's current timezone.

CURRENT_TZ="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
TZ_NAME="${1:-${HERMES_TIMEZONE:-${CURRENT_TZ:-UTC}}}"

if [[ -z "$TZ_NAME" ]]; then
  echo "Timezone nao informado e nao foi possivel detectar o timezone atual." >&2
  exit 1
fi

if [[ ! -e "/usr/share/zoneinfo/$TZ_NAME" ]]; then
  echo "Timezone invalido: $TZ_NAME" >&2
  echo "Exemplo: America/Sao_Paulo, Europe/Rome, UTC" >&2
  exit 1
fi

echo "[timezone] Configurando sistema/Hermes para $TZ_NAME..."

if command -v timedatectl >/dev/null 2>&1; then
  if [[ "$(id -u)" -eq 0 ]]; then
    timedatectl set-timezone "$TZ_NAME"
  elif command -v sudo >/dev/null 2>&1; then
    sudo timedatectl set-timezone "$TZ_NAME"
  else
    echo "Sem sudo. Configure o sistema manualmente ou execute com um usuario autorizado." >&2
    exit 1
  fi
fi

if command -v hermes >/dev/null 2>&1; then
  hermes config set timezone "$TZ_NAME" >/dev/null
fi

systemctl --user set-environment TZ="$TZ_NAME" HERMES_TIMEZONE="$TZ_NAME" 2>/dev/null || true
mkdir -p "$HOME/.config/environment.d"
cat > "$HOME/.config/environment.d/90-hermes-timezone.conf" <<EOF
TZ=$TZ_NAME
HERMES_TIMEZONE=$TZ_NAME
EOF

systemctl --user restart hermes-fast-router.service 2>/dev/null || true
systemctl --user restart hermes-core-health.service 2>/dev/null || true
systemctl --user restart hermes-gateway.service 2>/dev/null || true

echo "OK: timezone configurado para $TZ_NAME"
date '+%Y-%m-%d %H:%M:%S %Z %z'
