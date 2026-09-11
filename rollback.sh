#!/usr/bin/env bash
set -Eeuo pipefail
TARGET_USER="${HERMES_TARGET_USER:-${SUDO_USER:-$(id -un)}}"
TARGET_HOME="$(getent passwd "$TARGET_USER" 2>/dev/null | cut -d: -f6 || true)"
[[ -n "$TARGET_HOME" ]] || TARGET_HOME="$HOME"
HERMES_HOME="${HERMES_HOME:-$TARGET_HOME/.hermes}"
BACK_ROOT="$HERMES_HOME/backups"
LATEST="${1:-$(find "$BACK_ROOT" -maxdepth 1 -type d -name 'local-only-*' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n1 | cut -d' ' -f2-)}"
[[ -n "$LATEST" && -d "$LATEST" ]] || { echo "Nenhum backup local-only encontrado em $BACK_ROOT" >&2; exit 1; }
echo "Restaurando: $LATEST"
for rel in config.yaml .env auth.json cron/jobs.json; do
  if [[ -f "$LATEST/$rel" ]]; then
    mkdir -p "$HERMES_HOME/$(dirname "$rel")"
    cp -a "$LATEST/$rel" "$HERMES_HOME/$rel"
    echo "restaurado $rel"
  fi
done
if [[ "${EUID:-$(id -u)}" -eq 0 && "$TARGET_USER" != root ]]; then
  chown -R "$TARGET_USER:$(id -gn "$TARGET_USER")" "$HERMES_HOME/config.yaml" "$HERMES_HOME/.env" "$HERMES_HOME/auth.json" "$HERMES_HOME/cron/jobs.json" 2>/dev/null || true
fi
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  rm -f /etc/systemd/system/ollama.service.d/hermes-local-only.conf
  if [[ -f "$LATEST/systemd/ollama.service.d.conf" ]]; then
    mkdir -p /etc/systemd/system/ollama.service.d
    cp -a "$LATEST/systemd/ollama.service.d.conf" /etc/systemd/system/ollama.service.d/hermes-local-only.conf
  fi
  systemctl daemon-reload 2>/dev/null || true
  systemctl restart ollama 2>/dev/null || true
fi
if command -v hermes >/dev/null 2>&1; then
  if [[ "${EUID:-$(id -u)}" -eq 0 && "$TARGET_USER" != root ]]; then
    sudo -u "$TARGET_USER" -H env HERMES_HOME="$HERMES_HOME" hermes gateway restart >/dev/null 2>&1 || true
  else HERMES_HOME="$HERMES_HOME" hermes gateway restart >/dev/null 2>&1 || true; fi
fi
echo 'Rollback concluído.'
