#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HOME/.hermes/core-v2"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SYSTEMD_USER="$HOME/.config/systemd/user"
SCRIPTS="$HOME/.hermes/scripts"

log() { printf '[core-v2] %s\n' "$*"; }

ensure_venv_support() {
  local pyver pkg probe
  pyver="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  pkg="python${pyver}-venv"
  probe="$(mktemp -d)"
  if "$PYTHON_BIN" -m venv "$probe/test" >/dev/null 2>&1 && "$probe/test/bin/python" -m pip --version >/dev/null 2>&1; then
    rm -rf "$probe"; return 0
  fi
  rm -rf "$probe"
  log "Suporte completo a venv/pip ausente. Instalando $pkg e python3-pip..."
  if ! command -v apt-get >/dev/null 2>&1; then
    log "apt-get nao encontrado. Instale manualmente $pkg python3-pip e rode novamente."; exit 1
  fi
  if [ "$(id -u)" -eq 0 ]; then
    apt-get update && apt-get install -y "$pkg" python3-pip
  elif command -v sudo >/dev/null 2>&1; then
    sudo apt-get update && sudo apt-get install -y "$pkg" python3-pip
  else
    log "Sem sudo. Rode: apt-get install -y $pkg python3-pip"; exit 1
  fi
}

mkdir -p "$TARGET" "$TARGET/state" "$TARGET/logs" "$SYSTEMD_USER" "$SCRIPTS"
for file in \
  hermes_core.py tools.py planner.py health_monitor.py local_briefs.py \
  memory_store.py action_executor.py tool_registry.py recovery_engine.py event_bus.py; do
  cp "$ROOT/core_v2/$file" "$TARGET/$file"
done
cp "$ROOT/core_v2/requirements.txt" "$TARGET/requirements.txt"
cp "$ROOT/core_v2/config.example.yaml" "$TARGET/config.example.yaml"

if [ ! -f "$TARGET/config.yaml" ]; then
  cp "$TARGET/config.example.yaml" "$TARGET/config.yaml"
fi

ensure_venv_support
if [ -d "$TARGET/venv" ]; then
  if [ ! -x "$TARGET/venv/bin/python" ] || ! "$TARGET/venv/bin/python" -m pip --version >/dev/null 2>&1; then
    log "Removendo venv incompleto/quebrado..."; rm -rf "$TARGET/venv"
  fi
fi
if [ ! -x "$TARGET/venv/bin/python" ]; then
  log "Criando ambiente virtual..."; "$PYTHON_BIN" -m venv "$TARGET/venv"
fi
if ! "$TARGET/venv/bin/python" -m pip --version >/dev/null 2>&1; then
  log "pip ainda ausente no venv; tentando ensurepip..."; "$TARGET/venv/bin/python" -m ensurepip --upgrade
fi

log "Instalando dependencias..."
"$TARGET/venv/bin/python" -m pip install --upgrade pip
"$TARGET/venv/bin/python" -m pip install -r "$TARGET/requirements.txt"
chmod +x "$TARGET/hermes_core.py" "$TARGET/health_monitor.py" "$TARGET/local_briefs.py" "$TARGET/recovery_engine.py"

log "Instalando scripts locais de cron (no-agent)..."
make_wrapper() {
  local path="$1" mode="$2"
  cat > "$path" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "$TARGET/venv/bin/python" "$TARGET/local_briefs.py" "$mode"
EOF
  chmod +x "$path"
}
make_wrapper "$SCRIPTS/ai-daily-brief.sh" ai
make_wrapper "$SCRIPTS/marketing-leads-brief.sh" marketing
make_wrapper "$SCRIPTS/product-opportunity-brief.sh" product
make_wrapper "$SCRIPTS/financial-subscriptions-brief.sh" finance

log "Instalando health monitor + recovery engine..."
cat > "$SYSTEMD_USER/hermes-core-health.service" <<EOF
[Unit]
Description=Hermes Core v2.1 Autonomous Health + Recovery Monitor
After=network-online.target hermes-local-llm.service hermes-gateway.service

[Service]
Type=simple
ExecStart=$TARGET/venv/bin/python $TARGET/health_monitor.py
Restart=always
RestartSec=5
WorkingDirectory=$TARGET
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now hermes-core-health.service
systemctl --user restart hermes-core-health.service

log "Validando imports..."
(
  cd "$TARGET"
  "$TARGET/venv/bin/python" -c 'import httpx, psutil, yaml, feedparser; import tools, planner, local_briefs, memory_store, action_executor, tool_registry, recovery_engine, event_bus; print("dependencias Core v2.1 OK")'
)

log "Hermes Core v2.1 instalado em $TARGET"
echo "Testes rapidos:"
echo "  $TARGET/venv/bin/python $TARGET/hermes_core.py 'status da vps'"
echo "  $TARGET/venv/bin/python $TARGET/hermes_core.py 'ferramentas'"
echo "  $TARGET/venv/bin/python $TARGET/hermes_core.py 'corrija tudo'"
echo "  $TARGET/venv/bin/python $TARGET/hermes_core.py 'o que voce corrigiu?'"
echo "  systemctl --user status hermes-core-health.service --no-pager"
echo "Para migrar as crons existentes para no-agent:"
echo "  cd $ROOT && ./migrate-crons-local.sh"
