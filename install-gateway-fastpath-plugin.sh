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

_gateway_pids() {
  # Match real Python gateway processes. Avoid matching grep/shell helpers.
  ps -eo pid=,args= | awk '/[p]ython/ && /-m hermes_cli\.main gateway run/ {print $1}'
}

_stop_all_gateways() {
  # Primeiro use a propria CLI. Ela conhece o arquivo/lock interno usado pelo
  # gateway e consegue encerrar processos que um simples pkill pode deixar para
  # tras. Foi exatamente o caso observado com o PID manual 1450998.
  echo "[fastpath] Encerrando qualquer gateway antigo..."
  hermes gateway stop >/dev/null 2>&1 || true
  sleep 1

  local pids
  pids="$(_gateway_pids || true)"
  if [[ -n "$pids" ]]; then
    echo "[fastpath] Encerrando processos gateway remanescentes: $pids"
    kill $pids 2>/dev/null || true
    for _ in $(seq 1 10); do
      sleep 0.5
      pids="$(_gateway_pids || true)"
      [[ -z "$pids" ]] && break
    done
  fi

  pids="$(_gateway_pids || true)"
  if [[ -n "$pids" ]]; then
    echo "[fastpath] Forcando encerramento de gateways remanescentes: $pids"
    kill -9 $pids 2>/dev/null || true
    sleep 1
  fi

  pids="$(_gateway_pids || true)"
  if [[ -n "$pids" ]]; then
    echo "ERRO: ainda existem processos gateway apos tentativa de encerramento: $pids" >&2
    ps -fp $pids >&2 || true
    exit 1
  fi

  # Limpa apenas o pid auxiliar que nos mesmos criamos em modo nohup. A CLI
  # acima e responsavel por qualquer lock interno proprio do Hermes.
  rm -f "$HOME/.hermes/gateway.pid" 2>/dev/null || true
}

_restart_systemd_mode() {
  echo "[fastpath] Gateway possui user service; reconciliando processo manual + systemd..."

  # Impede o Restart= do service de competir com a limpeza do processo manual.
  systemctl --user stop hermes-gateway.service 2>/dev/null || true
  sleep 1
  _stop_all_gateways
  systemctl --user reset-failed hermes-gateway.service 2>/dev/null || true
  systemctl --user start hermes-gateway.service

  for _ in $(seq 1 30); do
    if systemctl --user is-active --quiet hermes-gateway.service; then
      # active pode acontecer por alguns segundos antes de falhar por lock.
      # Exigimos tambem que exista exatamente um processo real do gateway.
      local pids count
      pids="$(_gateway_pids || true)"
      count="$(printf '%s\n' "$pids" | sed '/^$/d' | wc -l | tr -d ' ')"
      if [[ "$count" == "1" ]]; then
        sleep 2
        if systemctl --user is-active --quiet hermes-gateway.service; then
          return 0
        fi
      fi
    fi
    sleep 0.5
  done

  echo "ERRO: hermes-gateway.service nao estabilizou." >&2
  systemctl --user status hermes-gateway.service --no-pager >&2 || true
  journalctl --user -u hermes-gateway.service -n 120 --no-pager >&2 || true
  exit 1
}

_restart_process_mode() {
  echo "[fastpath] Gateway nao usa systemd nesta VPS; reiniciando processo direto..."
  _stop_all_gateways

  if [[ ! -x "$GATEWAY_PY" ]]; then
    echo "ERRO: Python do gateway nao encontrado em $GATEWAY_PY" >&2
    exit 1
  fi

  : > "$GATEWAY_LOG"
  nohup "$GATEWAY_PY" -m hermes_cli.main gateway run --replace > "$GATEWAY_LOG" 2>&1 </dev/null &
  echo $! > "$HOME/.hermes/gateway.pid"

  for _ in $(seq 1 30); do
    local pids count
    pids="$(_gateway_pids || true)"
    count="$(printf '%s\n' "$pids" | sed '/^$/d' | wc -l | tr -d ' ')"
    if [[ "$count" == "1" ]]; then
      return 0
    fi
    sleep 0.5
  done

  echo "ERRO: gateway nao subiu de forma estavel em modo processo." >&2
  tail -n 100 "$GATEWAY_LOG" >&2 || true
  exit 1
}

echo "[fastpath] Reiniciando gateway..."
START_TS="$(date '+%Y-%m-%d %H:%M:%S')"
if _has_user_unit; then
  _restart_systemd_mode
else
  _restart_process_mode
fi

echo "[fastpath] Verificando carregamento no runtime..."
loaded=0
for _ in $(seq 1 30); do
  if _has_user_unit; then
    if journalctl --user -u hermes-gateway.service --since "$START_TS" --no-pager 2>/dev/null | grep -q 'HERMES CORE FASTPATH plugin registered'; then
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
  echo "Processos gateway atuais:" >&2
  pids="$(_gateway_pids || true)"
  [[ -z "$pids" ]] || ps -fp $pids >&2 || true
  echo "Ultimas linhas do gateway:" >&2
  if _has_user_unit; then
    journalctl --user -u hermes-gateway.service --since "$START_TS" --no-pager >&2 || true
  else
    tail -n 120 "$GATEWAY_LOG" >&2 || true
  fi
  exit 1
fi

echo "OK: gateway fastpath plugin instalado, habilitado E carregado no runtime."
echo "Mensagens normais do Telegram agora passam pelo Hermes Core; comandos / continuam pertencendo ao gateway."
