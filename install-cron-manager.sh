#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HOME/.hermes/core-v2"
SCRIPTS="$HOME/.hermes/scripts"

[[ -x "$TARGET/venv/bin/python" ]] || {
  echo "Hermes Core v2 ainda não está instalado. Rode ./install-core-v2.sh primeiro." >&2
  exit 1
}

mkdir -p "$TARGET/state" "$SCRIPTS"
cp "$ROOT/core_v2/cron_manager.py" "$TARGET/cron_manager.py"
cp "$ROOT/core_v2/cron_task_runner.py" "$TARGET/cron_task_runner.py"
chmod 700 "$TARGET/cron_manager.py" "$TARGET/cron_task_runner.py"

# Preserve managed task state across updates.
if [[ ! -f "$TARGET/state/managed_crons.json" ]]; then
  printf '{}\n' > "$TARGET/state/managed_crons.json"
  chmod 600 "$TARGET/state/managed_crons.json"
fi

# Validate Python before touching the router.
"$TARGET/venv/bin/python" -m py_compile \
  "$TARGET/cron_manager.py" \
  "$TARGET/cron_task_runner.py"

chmod +x "$ROOT/install-fast-router.sh"
"$ROOT/install-fast-router.sh"

echo
echo "=== Telegram Cron Manager instalado ==="
echo "Teste local rápido:"
echo "  $TARGET/venv/bin/python $TARGET/cron_manager.py --text-b64 \$(printf '%s' 'quais rotinas eu tenho?' | base64 -w0)"
echo
echo "Agora teste pelo Telegram:"
echo "  crie uma rotina todo dia às 8h para me mandar notícias de Flutter"
echo "  quais rotinas eu tenho?"
echo "  pause a rotina <nome>"
