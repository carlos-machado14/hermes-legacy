#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HOME/.hermes/core-v2"
mkdir -p "$TARGET" "$TARGET/state" "$TARGET/logs"
cp "$ROOT/core_v2/hermes_core.py" "$TARGET/hermes_core.py"
cp "$ROOT/core_v2/requirements.txt" "$TARGET/requirements.txt"
cp "$ROOT/core_v2/config.example.yaml" "$TARGET/config.example.yaml"
if [ ! -f "$TARGET/config.yaml" ]; then
  cp "$TARGET/config.example.yaml" "$TARGET/config.yaml"
fi
python3 -m venv "$TARGET/venv"
"$TARGET/venv/bin/pip" install --upgrade pip
"$TARGET/venv/bin/pip" install -r "$TARGET/requirements.txt"
chmod +x "$TARGET/hermes_core.py"
echo "Hermes Core v2 instalado em $TARGET"
echo "Teste: $TARGET/venv/bin/python $TARGET/hermes_core.py 'status da vps'"
