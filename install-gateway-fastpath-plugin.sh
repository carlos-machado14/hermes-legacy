#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$ROOT/plugins/hermes-core-fastpath"
DST="$HOME/.hermes/plugins/hermes-core-fastpath"
GATEWAY_LOG="$HOME/.hermes/gateway.log"
GATEWAY_PY="$HOME/.hermes/hermes-agent/venv/bin/python"
CONFIG="$HOME/.hermes/config.yaml"

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

if [[ ! -x "$GATEWAY_PY" ]]; then
  echo "ERRO: Python do gateway nao encontrado em $GATEWAY_PY" >&2
  exit 1
fi

"$GATEWAY_PY" -m py_compile "$DST/__init__.py"
hermes plugins doctor "$DST" --ci

echo "[fastpath] Habilitando plugin..."
if command -v timeout >/dev/null 2>&1; then
  timeout 20s hermes plugins enable hermes-core-fastpath --no-allow-tool-override </dev/null
else
  hermes plugins enable hermes-core-fastpath --no-allow-tool-override </dev/null
fi

# Garanta diretamente no config usado pelo gateway. Em algumas versoes do Hermes
# a CLI pode reportar o plugin como habilitado enquanto um disabled legado ou uma
# configuracao divergente impede o carregamento no processo do gateway.
echo "[fastpath] Garantindo enablement no config.yaml..."
"$GATEWAY_PY" - "$CONFIG" <<'PY'
from pathlib import Path
import sys
import yaml

path = Path(sys.argv[1])
if path.exists():
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except Exception as exc:
        raise SystemExit(f"config.yaml invalido: {exc}")
else:
    data = {}

plugins = data.setdefault('plugins', {})
enabled = list(plugins.get('enabled') or [])
disabled = list(plugins.get('disabled') or [])
name = 'hermes-core-fastpath'
if name not in enabled:
    enabled.append(name)
disabled = [x for x in disabled if str(x) != name]
plugins['enabled'] = sorted({str(x) for x in enabled if str(x).strip()})
plugins['disabled'] = sorted({str(x) for x in disabled if str(x).strip()})
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')
print('config plugin enabled=', name in plugins['enabled'], 'disabled=', name in plugins['disabled'])
PY

echo "[fastpath] Validando plugin..."
if ! hermes plugins list --plain 2>/dev/null | grep -qi 'hermes-core-fastpath'; then
  echo "ERRO: hermes-core-fastpath nao apareceu em 'hermes plugins list --plain'." >&2
  exit 1
fi

# Preflight com o MESMO Python usado pelo gateway. Hermes pode expor `hooks`
# como lista de nomes ou apenas como contagem inteira, dependendo da versao.
echo "[fastpath] Preflight de discovery no runtime do gateway..."
"$GATEWAY_PY" - <<'PY'
from hermes_cli.plugins import discover_plugins, get_plugin_manager

discover_plugins(force=True)
pm = get_plugin_manager()
rows = pm.list_plugins()
row = next((r for r in rows if r.get('name') == 'hermes-core-fastpath' or r.get('key') == 'hermes-core-fastpath'), None)
if not row:
    raise SystemExit('ERRO: plugin nao descoberto pelo Python do gateway')
print('plugin=', row.get('name') or row.get('key'), 'enabled=', row.get('enabled'), 'hooks=', row.get('hooks'), 'error=', row.get('error'))
if not row.get('enabled'):
    raise SystemExit('ERRO: plugin descoberto mas nao esta enabled no runtime')

raw_hooks = row.get('hooks')
if isinstance(raw_hooks, int):
    hooks_count = raw_hooks
    hook_names = set()
else:
    hook_names = set(raw_hooks or [])
    hooks_count = len(hook_names)

if hooks_count < 1:
    raise SystemExit('ERRO: nenhum hook registrado no runtime preflight')
if hook_names and 'pre_gateway_dispatch' not in hook_names:
    raise SystemExit('ERRO: pre_gateway_dispatch nao aparece entre os hooks registrados')
if row.get('error'):
    raise SystemExit(f"ERRO: plugin com erro no preflight: {row.get('error')}")
print('preflight hooks_count=', hooks_count, 'names=', sorted(hook_names) if hook_names else '(runtime exposes count only)')
PY

_has_user_unit() {
  systemctl --user list-unit-files hermes-gateway.service --no-legend 2>/dev/null | grep -q '^hermes-gateway\.service'
}

_gateway_pids() {
  ps -eo pid=,args= | awk '/[p]ython/ && /-m hermes_cli\.main gateway run/ {print $1}'
}

_stop_all_gateways() {
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
  rm -f "$HOME/.hermes/gateway.pid" 2>/dev/null || true
}

_restart_systemd_mode() {
  echo "[fastpath] Gateway possui user service; reconciliando processo manual + systemd..."
  systemctl --user stop hermes-gateway.service 2>/dev/null || true
  sleep 1
  _stop_all_gateways
  systemctl --user reset-failed hermes-gateway.service 2>/dev/null || true
  systemctl --user start hermes-gateway.service

  for _ in $(seq 1 30); do
    if systemctl --user is-active --quiet hermes-gateway.service; then
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

echo "[fastpath] Verificando gateway apos restart..."
if _has_user_unit; then
  if ! systemctl --user is-active --quiet hermes-gateway.service; then
    echo "ERRO: gateway nao esta ativo apos restart." >&2
    exit 1
  fi
else
  pids="$(_gateway_pids || true)"
  [[ -n "$pids" ]] || { echo "ERRO: processo gateway ausente apos restart." >&2; exit 1; }
fi

if _has_user_unit; then
  journalctl --user -u hermes-gateway.service --since "$START_TS" --no-pager 2>/dev/null | grep -i 'HERMES CORE FASTPATH' || true
else
  grep -i 'HERMES CORE FASTPATH' "$GATEWAY_LOG" 2>/dev/null || true
fi

echo "OK: fastpath validado pelo Plugin Doctor + discovery do mesmo Python do gateway."
echo "OK: gateway reiniciado e estavel com hermes-core-fastpath habilitado no config.yaml."
echo "Mensagens normais do Telegram passam pelo Hermes Core; comandos / continuam pertencendo ao gateway."
