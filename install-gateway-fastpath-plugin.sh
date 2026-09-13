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
rm -rf "$DST/__pycache__"
cp "$SRC/plugin.yaml" "$DST/plugin.yaml"
cp "$SRC/__init__.py" "$DST/__init__.py"
chmod 700 "$DST/__init__.py"
chmod 600 "$DST/plugin.yaml"

if ! command -v hermes >/dev/null 2>&1; then
  echo "hermes CLI nao encontrado" >&2
  exit 1
fi

# Doctor precisa passar; nao escondemos erro de plugin.
hermes plugins doctor "$DST" --ci

# Habilita sem qualquer prompt interativo. O fastpath nao substitui tools built-in.
echo "[fastpath] Habilitando plugin..."
if command -v timeout >/dev/null 2>&1; then
  timeout 20s hermes plugins enable hermes-core-fastpath --no-allow-tool-override </dev/null
else
  hermes plugins enable hermes-core-fastpath --no-allow-tool-override </dev/null
fi

# Confirma em modo plain para evitar UI interativa/Rich.
echo "[fastpath] Validando allow-list..."
if ! hermes plugins list --plain 2>/dev/null | grep -qi 'hermes-core-fastpath'; then
  echo "ERRO: hermes-core-fastpath nao apareceu em 'hermes plugins list --plain'." >&2
  exit 1
fi

# Reinicia somente depois de toda validacao local passar.
echo "[fastpath] Reiniciando gateway..."
systemctl --user restart hermes-gateway.service 2>/dev/null || hermes gateway restart
sleep 2

if ! systemctl --user is-active --quiet hermes-gateway.service 2>/dev/null; then
  echo "ERRO: hermes-gateway nao ficou ativo apos instalar o fastpath." >&2
  systemctl --user status hermes-gateway.service --no-pager || true
  exit 1
fi

echo "OK: gateway fastpath plugin instalado e habilitado."
echo "Ele intercepta comandos operacionais/crons antes da sessao normal."
echo "Teste no Telegram: status da vps"
