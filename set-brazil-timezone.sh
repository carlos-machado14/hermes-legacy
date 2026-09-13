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

# Mantém a timezone explícita no ambiente dos serviços Hermes desta sessão.
systemctl --user set-environment TZ="$TZ_NAME"

# Persistência para novas sessões do systemd --user.
mkdir -p "$HOME/.config/environment.d"
printf 'TZ=%s\n' "$TZ_NAME" > "$HOME/.config/environment.d/90-hermes-timezone.conf"

# Reinicia componentes que calculam/agendam horários.
systemctl --user restart hermes-gateway.service 2>/dev/null || true
systemctl --user restart hermes-fast-router.service 2>/dev/null || true
systemctl --user restart hermes-core-health.service 2>/dev/null || true

printf '\n[timezone] Sistema:\n'
timedatectl | sed -n '1,8p'
printf '\n[timezone] Data/hora efetiva:\n'
date '+%d/%m/%Y %H:%M:%S %Z %z'
printf '\n[timezone] Próximas crons:\n'
hermes cron status 2>/dev/null || true

echo
echo "OK: horários do Hermes passam a usar Brasília ($TZ_NAME)."
