#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PLUGIN_SRC="$ROOT/plugins/hermes-core-fastpath"
PLUGIN_DST="$HERMES_HOME/plugins/hermes-core-fastpath"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$HERMES_HOME/backups/hermes-core-fastpath-$STAMP"

log() { printf '[runtime-sync] %s\n' "$*"; }

if [ ! -f "$PLUGIN_SRC/__init__.py" ]; then
  log "Plugin fonte nao encontrado em $PLUGIN_SRC"
  exit 1
fi

plugin_valid() {
  local path="$1"
  command -v hermes >/dev/null 2>&1 || return 1
  hermes plugins doctor "$path" --ci >/dev/null 2>&1
}

find_valid_backup() {
  local candidate
  while IFS= read -r candidate; do
    [ -d "$candidate" ] || continue
    if plugin_valid "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done < <(find "$HERMES_HOME/backups" -maxdepth 1 -type d -name 'hermes-core-fastpath-*' -printf '%T@ %p\n' 2>/dev/null | sort -nr | cut -d' ' -f2-)
  return 1
}

log "Atualizando Hermes Core..."
chmod +x "$ROOT/install-core-v2.sh"
"$ROOT/install-core-v2.sh"

mkdir -p "$HERMES_HOME/plugins" "$HERMES_HOME/backups"

# O manifest valido e gerenciado pelo proprio Hermes. Nao apagamos mais o
# diretorio inteiro do plugin, pois isso remove metadados de discovery que o
# `hermes plugins doctor` exige.
if [ -d "$PLUGIN_DST" ]; then
  mkdir -p "$BACKUP"
  cp -a "$PLUGIN_DST/." "$BACKUP/" 2>/dev/null || true
fi

# Se a execucao anterior ja deixou o plugin invalido, recupera automaticamente o
# backup mais recente que ainda passa no doctor antes de aplicar o novo codigo.
if command -v hermes >/dev/null 2>&1 && ! plugin_valid "$PLUGIN_DST"; then
  log "Plugin atual sem manifest valido; procurando backup recuperavel..."
  RECOVERY="$(find_valid_backup || true)"
  if [ -z "$RECOVERY" ]; then
    log "ERRO: nao encontrei backup valido do plugin."
    log "Nao vou reiniciar o gateway para evitar piorar o runtime."
    log "Envie a saida de: find $HERMES_HOME/backups -maxdepth 2 -type f | sort"
    exit 3
  fi
  log "Recuperando manifest/runtime base a partir de: $RECOVERY"
  rm -rf "$PLUGIN_DST"
  mkdir -p "$PLUGIN_DST"
  cp -a "$RECOVERY/." "$PLUGIN_DST/"
fi

log "Atualizando somente o codigo versionado do plugin, preservando o manifest do Hermes..."
mkdir -p "$PLUGIN_DST"
cp "$PLUGIN_SRC/__init__.py" "$PLUGIN_DST/__init__.py"
if [ -f "$PLUGIN_SRC/plugin.yaml" ]; then
  cp "$PLUGIN_SRC/plugin.yaml" "$PLUGIN_DST/plugin.yaml"
fi
chmod -R u+rwX,go-rwx "$PLUGIN_DST" 2>/dev/null || true

log "Validando plugin instalado..."
if command -v hermes >/dev/null 2>&1; then
  if ! hermes plugins doctor "$PLUGIN_DST" --ci; then
    log "ERRO: plugin continua invalido apos sincronizacao. Restaurando backup desta execucao..."
    if [ -d "$BACKUP" ] && plugin_valid "$BACKUP"; then
      rm -rf "$PLUGIN_DST"
      mkdir -p "$PLUGIN_DST"
      cp -a "$BACKUP/." "$PLUGIN_DST/"
      log "Rollback concluido; gateway nao sera reiniciado."
    fi
    exit 4
  fi
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

log "Checando se ainda existe a mensagem antiga no plugin ativo..."
if grep -R -n -F 'Não consegui obter uma resposta confiável dentro do limite local.' "$PLUGIN_DST" 2>/dev/null; then
  log "ERRO: mensagem do runtime antigo ainda existe no plugin ativo."
  exit 2
fi

log "Runtime sincronizado e manifest preservado."
log "Backup desta execucao: $BACKUP"
