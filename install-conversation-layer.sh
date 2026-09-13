#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HOME/.hermes/core-v2"
mkdir -p "$TARGET" "$TARGET/state"
for file in conversation_memory.py contextual_router.py core_entry.py; do
  cp "$ROOT/core_v2/$file" "$TARGET/$file"
done
chmod +x "$TARGET/core_entry.py"
echo "[conversation] camada conversacional instalada"
