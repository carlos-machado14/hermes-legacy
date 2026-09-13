#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$ROOT/plugins/hermes-core-fastpath"
DST="$HOME/.hermes/plugins/hermes-core-fastpath"

[[ -f "$SRC/plugin.yaml" && -f "$SRC/__init__.py" ]] || {
  echo "Plugin source ausente em $SRC" >&2
  exit 1
}

mkdir -p "$DST"
cp "$SRC/plugin.yaml" "$DST/plugin.yaml"
cp "$SRC/__init__.py" "$DST/__init__.py"
chmod 700 "$DST/__init__.py"
chmod 600 "$DST/plugin.yaml"

if command -v hermes >/dev/null 2>&1; then
  hermes plugins enable hermes-core-fastpath >/dev/null 2>&1 || true
  hermes plugins doctor "$DST" --ci || true
fi

systemctl --user restart hermes-gateway.service 2>/dev/null || hermes gateway restart || true
sleep 2

echo "OK: gateway fastpath plugin instalado."
echo "Ele intercepta comandos operacionais/crons ANTES da sessao e da compressao de contexto."
echo "Teste no Telegram: status da vps"
