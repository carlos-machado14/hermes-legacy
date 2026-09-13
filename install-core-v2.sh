#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HOME/.hermes/core-v2"
PYTHON_BIN="${PYTHON_BIN:-python3}"

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

mkdir -p "$TARGET" "$TARGET/state" "$TARGET/logs"
cp "$ROOT/core_v2/hermes_core.py" "$TARGET/hermes_core.py"
cp "$ROOT/core_v2/requirements.txt" "$TARGET/requirements.txt"
cp "$ROOT/core_v2/config.example.yaml" "$TARGET/config.example.yaml"

if [ ! -f "$TARGET/config.yaml" ]; then
  cp "$TARGET/config.example.yaml" "$TARGET/config.yaml"
fi

ensure_venv_support

# Recreate any environment that is missing either Python or pip.
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

# Last-resort bootstrap for unusual Debian/Ubuntu images.
if ! "$TARGET/venv/bin/python" -m pip --version >/dev/null 2>&1; then
  log "pip ainda ausente no venv; tentando ensurepip..."
  "$TARGET/venv/bin/python" -m ensurepip --upgrade
fi

log "Instalando dependencias..."
"$TARGET/venv/bin/python" -m pip install --upgrade pip
"$TARGET/venv/bin/python" -m pip install -r "$TARGET/requirements.txt"

chmod +x "$TARGET/hermes_core.py"

log "Validando imports..."
"$TARGET/venv/bin/python" -c 'import httpx, psutil, yaml; print("dependencias OK")'

log "Hermes Core v2 instalado em $TARGET"
echo "Teste: $TARGET/venv/bin/python $TARGET/hermes_core.py 'status da vps'"
