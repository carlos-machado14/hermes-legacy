#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HOME/.hermes/core-v2"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SYSTEMD_USER="$HOME/.config/systemd/user"

log() { printf '[core-v2] %s\n' "$*"; }

ensure_venv_support() {
  local pyver pkg probe
  pyver="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  pkg="python${pyver}-venv"
  probe="$(mktemp -d)"

  if "$PYTHON_BIN" -m venv "$probe/test" >/dev/null 2>&1 \
    && "$probe/test/bin/python" -m pip --version >/dev/null 2>&1; then
    rm -rf "$probe"
    return 0
  fi
  rm -rf "$probe"

  log "Suporte completo a venv/pip ausente. Instalando $pkg e python3-pip..."
  if ! command -v apt-get >/dev/null 2>&1; then
    log "apt-get nao encontrado. Instale manualmente $pkg python3-pip e rode novamente."
    exit 1
  fi

  if [ "$(id -u)" -eq 0 ]; then
    apt-get update
    apt-get install -y "$pkg" python3-pip
  elif command -v sudo >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y "$pkg" python3-pip
  else
    log "Sem sudo. Rode: apt-get install -y $pkg python3-pip"
    exit 1
  fi
}

mkdir -p "$TARGET" "$TARGET/state" "$TARGET/logs" "$SYSTEMD_USER"
cp "$ROOT/core_v2/hermes_core.py" "$TARGET/hermes_core.py"
cp "$ROOT/core_v2/tools.py" "$TARGET/tools.py"
cp "$ROOT/core_v2/planner.py" "$TARGET/planner.py"
cp "$ROOT/core_v2/health_monitor.py" "$TARGET/health_monitor.py"
cp "$ROOT/core_v2/requirements.txt" "$TARGET/requirements.txt"
cp "$ROOT/core_v2/config.example.yaml" "$TARGET/config.example.yaml"

if [ ! -f "$TARGET/config.yaml" ]; then
  cp "$TARGET/config.example.yaml" "$TARGET/config.yaml"
fi

ensure_venv_support

if [ -d "$TARGET/venv" ]; then
  if [ ! -x "$TARGET/venv/bin/python" ] \
    || ! "$TARGET/venv/bin/python" -m pip --version >/dev/null 2>&1; then
    log "Removendo venv incompleto/quebrado..."
    rm -rf "$TARGET/venv"
  fi
fi

if [ ! -x "$TARGET/venv/bin/python" ]; then
  log "Criando ambiente virtual..."
  "$PYTHON_BIN" -m venv "$TARGET/venv"
fi

if ! "$TARGET/venv/bin/python" -m pip --version >/dev/null 2>&1; then
  log "pip ainda ausente no venv; tentando ensurepip..."
  "$TARGET/venv/bin/python" -m ensurepip --upgrade
fi

log "Instalando dependencias..."
"$TARGET/venv/bin/python" -m pip install --upgrade pip
"$TARGET/venv/bin/python" -m pip install -r "$TARGET/requirements.txt"

chmod +x "$TARGET/hermes_core.py" "$TARGET/health_monitor.py"

log "Instalando health monitor..."
cat > "$SYSTEMD_USER/hermes-core-health.service" <<EOF
[Unit]
Description=Hermes Core v2 Self-Healing Health Monitor
After=network-online.target hermes-local-llm.service hermes-gateway.service

[Service]
Type=simple
ExecStart=$TARGET/venv/bin/python $TARGET/health_monitor.py
Restart=always
RestartSec=5
WorkingDirectory=$TARGET

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now hermes-core-health.service

log "Validando imports..."
"$TARGET/venv/bin/python" -c 'import httpx, psutil, yaml; import tools, planner; print("dependencias OK")'

log "Hermes Core v2 instalado em $TARGET"
echo "Testes:"
echo "  $TARGET/venv/bin/python $TARGET/hermes_core.py 'status da vps'"
echo "  $TARGET/venv/bin/python $TARGET/hermes_core.py 'verifique por que minhas crons estao falhando'"
echo "  systemctl --user status hermes-core-health.service --no-pager"
