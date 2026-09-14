#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$ROOT/plugins/hermes-core-fastpath"
DST="$HOME/.hermes/plugins/hermes-core-fastpath"
GATEWAY_LOG="$HOME/.hermes/gateway.log"
GATEWAY_PY="$HOME/.hermes/hermes-agent/venv/bin/python"

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

hermes plugins doctor "$DST" --ci

echo "[fastpath] Habilitando plugin..."
if command -v timeout >/dev/null 2>&1; then
  timeout 20s hermes plugins enable hermes-core-fastpath --no-allow-tool-override </dev/null
else
  hermes plugins enable hermes-core-fastpath --no-allow-tool-override </dev/null
fi

echo "[fastpath] Validando plugin..."
if ! hermes plugins list --plain 2>/dev/null | grep -qi 'hermes-core-fastpath'; then
  echo "ERRO: hermes-core-fastpath nao apareceu em 'hermes plugins list --plain'." >&2
  exit 1
fi

_has_user_unit() {
  systemctl --user list-unit-files hermes-gateway.service --no-legend 2>/dev/null | grep -q '^hermes-gateway\.service'
}

_kill_stray_gateway() {
  # Remove somente gateways executados fora do systemd. O problema observado na
  # VPS foi exatamente um processo manual antigo mantendo o lock/PID enquanto o
  # user service tentava reiniciar em loop.
  local pids
  pids="$(pgrep -f 'hermes_cli\.main gateway run' 2>/dev/null || true)"
  [[ -z "$pids" ]] && return 0
  echo "[fastpath] Encerrando gateway antigo fora do controle esperado: $pids"
  kill $pids 2>/dev/null || true
  for _ in $(seq 1 10); do
    pgrep -f 'hermes_cli\.main gateway run' >/dev/null 2>&1 || return 0
    sleep 0.5
  done
  pids="$(pgrep -f 'hermes_cli\.main gateway run' 2>/dev/null || true)"
  [[ -z "$pids" ]] || kill -9 $pids 2>/dev/null || true
}

_restart_systemd_mode() {
  echo "[fastpath] Gateway possui user service; reconciliando processo manual + systemd..."

  # Pare primeiro o service para impedir o Restart= de disputar com o processo
  # manual antigo. Depois remova qualquer gateway remanescente e inicie uma
  # unica instancia limpa pelo systemd.
  systemctl --user stop hermes-gateway.service 2>/dev/null || true
  sleep 1
  _kill_stray_gateway
  rm -f "$HOME/.hermes/gateway.pid" 2>/dev/null || true
  systemctl --user reset-failed hermes-gateway.service 2>/dev/null || true
  systemctl --user start hermes-gateway.service

  for _ in $(seq 1 20); do
    if systemctl --user is-active --quiet hermes-gateway.service; then
      return 0
    fi
    sleep 0.5
  done

  echo "ERRO: hermes-gateway.service nao ficou ativo." >&2
  systemctl --user status hermes-gateway.service --no-pager >&2 || true
  journalctl --user -u hermes-gateway.service -n 100 --no-pager >&2 || true
  exit 1
}

_restart_process_mode() {
  echo "[fastpath] Gateway nao usa systemd nesta VPS; reiniciando processo direto..."
  _kill_stray_gateway
  sleep 1

  if [[ ! -x "$GATEWAY_PY" ]]; then
    echo "ERRO: Python do gateway nao encontrado em $GATEWAY_PY" >&2
    exit 1
  fi

  : > "$GATEWAY_LOG"
  nohup "$GATEWAY_PY" -m hermes_cli.main gateway run > "$GATEWAY_LOG" 2>&1 </dev/null &
  echo $! > "$HOME/.hermes/gateway.pid"

  for _ in $(seq 1 20); do
    if pgrep -f 'hermes_cli\.main gateway run' >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done

  echo "ERRO: gateway nao subiu em modo processo." >&2
  tail -n 80 "$GATEWAY_LOG" >&2 || true
  exit 1
}

echo "[fastpath] Reiniciando gateway..."
if _has_user_unit; then
  _restart_systemd_mode
else
  _restart_process_mode
fi

echo "[fastpath] Verificando carregamento no runtime..."
loaded=0
for _ in $(seq 1 20); do
  if _has_user_unit; then
    if journalctl --user -u hermes-gateway.service --since '-2 minutes' --no-pager 2>/dev/null | grep -q 'HERMES CORE FASTPATH plugin registered'; then
      loaded=1
      break
    fi
  else
    if grep -q 'HERMES CORE FASTPATH plugin registered' "$GATEWAY_LOG" 2>/dev/null; then
      loaded=1
      break
    fi
  fi
  sleep 0.5
done

if [[ "$loaded" != "1" ]]; then
  echo "ERRO: gateway subiu, mas o hook hermes-core-fastpath nao foi confirmado no runtime." >&2
  echo "Ultimas linhas do gateway:" >&2
  if _has_user_unit; then
    journalctl --user -u hermes-gateway.service -n 120 --no-pager >&2 || true
  else
    tail -n 120 "$GATEWAY_LOG" >&2 || true
  fi
  exit 1
fi

echo "OK: gateway fastpath plugin instalado, habilitado E carregado no runtime."
echo "Mensagens normais do Telegram agora passam pelo Hermes Core; comandos / continuam pertencendo ao gateway."
