#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN_SRC="$ROOT/plugins/hermes-core-fastpath"
PLUGIN_DST="$HERMES_HOME/plugins/hermes-core-fastpath"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$HERMES_HOME/backups/hermes-core-fastpath-$STAMP"

log() { printf '[runtime-sync] %s\n' "$*"; }

if [ ! -f "$PLUGIN_SRC/__init__.py" ] || [ ! -f "$PLUGIN_SRC/plugin.yaml" ]; then
  log "Plugin fonte nao encontrado em $PLUGIN_SRC"
  exit 1
fi

log "Atualizando Hermes Core..."
chmod +x "$ROOT/install-core-v2.sh"
"$ROOT/install-core-v2.sh"

log "Sincronizando plugin do gateway que realmente recebe as mensagens do Telegram..."
mkdir -p "$HERMES_HOME/plugins" "$HERMES_HOME/backups"
if [ -d "$PLUGIN_DST" ]; then
  mkdir -p "$BACKUP"
  cp -a "$PLUGIN_DST/." "$BACKUP/" 2>/dev/null || true
fi
rm -rf "$PLUGIN_DST"
mkdir -p "$PLUGIN_DST"
cp -a "$PLUGIN_SRC/." "$PLUGIN_DST/"
chmod -R u+rwX,go-rwx "$PLUGIN_DST" 2>/dev/null || true

log "Validando plugin instalado..."
if command -v hermes >/dev/null 2>&1; then
  hermes plugins doctor "$PLUGIN_DST" --ci
else
  log "Hermes CLI nao encontrado no PATH; validacao via doctor ignorada."
fi

log "Reiniciando gateway para descarregar o codigo antigo da memoria..."
if systemctl --user list-unit-files 2>/dev/null | grep -q '^hermes-gateway.service'; then
  systemctl --user restart hermes-gateway.service
elif command -v hermes >/dev/null 2>&1; then
  hermes gateway restart
else
  log "Nao consegui localizar o gerenciador do gateway."
  exit 1
fi

sleep 2

log "Versao instalada:"
cat "$PLUGIN_DST/plugin.yaml"

echo
log "Checando se ainda existe a mensagem antiga no plugin ativo..."
if grep -R -n -F 'Não consegui obter uma resposta confiável dentro do limite local.' "$PLUGIN_DST" 2>/dev/null; then
  log "ERRO: mensagem do runtime antigo ainda existe no plugin ativo."
  exit 2
fi

log "Runtime sincronizado. O gateway agora usa exatamente o plugin versionado no repo."
log "Backup anterior: $BACKUP"
