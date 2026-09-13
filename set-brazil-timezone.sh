#!/usr/bin/env bash
set -Eeuo pipefail

TZ_NAME="America/Sao_Paulo"

echo "[timezone] Configurando VPS/Hermes para $TZ_NAME..."

if command -v timedatectl >/dev/null 2>&1; then
  if [[ "$(id -u)" -eq 0 ]]; then
    timedatectl set-timezone "$TZ_NAME"
  elif command -v sudo >/dev/null 2>&1; then
    sudo timedatectl set-timezone "$TZ_NAME"
  else
    echo "Sem sudo. Rode manualmente: timedatectl set-timezone $TZ_NAME" >&2
    exit 1
  fi
else
  echo "timedatectl não encontrado." >&2
  exit 1
fi

# Hermes usa primeiro HERMES_TIMEZONE e depois `timezone` do config.yaml.
# Definimos ambos para evitar que o scheduler continue usando um offset antigo.
if command -v hermes >/dev/null 2>&1; then
  hermes config set timezone "$TZ_NAME" >/dev/null
fi

systemctl --user set-environment TZ="$TZ_NAME" HERMES_TIMEZONE="$TZ_NAME"

# Persistência para novas sessões do systemd --user.
mkdir -p "$HOME/.config/environment.d"
cat > "$HOME/.config/environment.d/90-hermes-timezone.conf" <<EOF
TZ=$TZ_NAME
HERMES_TIMEZONE=$TZ_NAME
EOF

# Reinicia componentes que calculam/agendam horários depois da config explícita.
systemctl --user restart hermes-fast-router.service 2>/dev/null || true
systemctl --user restart hermes-core-health.service 2>/dev/null || true
systemctl --user restart hermes-gateway.service 2>/dev/null || true
sleep 2

printf '\n[timezone] Sistema:\n'
timedatectl | sed -n '1,8p'
printf '\n[timezone] Data/hora efetiva:\n'
date '+%d/%m/%Y %H:%M:%S %Z %z'
printf '\n[timezone] Hermes config:\n'
hermes config get timezone 2>/dev/null || true
printf '\n[timezone] Próximas crons:\n'
hermes cron status 2>/dev/null || true

echo
echo "OK: Hermes e VPS configurados explicitamente para Brasília ($TZ_NAME)."
