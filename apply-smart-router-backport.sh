#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Run as the Hermes user, not root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export HERMES_HOME
HERMES_BIN="${HERMES_BIN:-$(command -v hermes || true)}"
[[ -n "$HERMES_BIN" ]] || { echo "Hermes CLI not found" >&2; exit 1; }

PATCH="$SCRIPT_DIR/patches/apply_core_tool_defer_backport.py"
SMART="$SCRIPT_DIR/smart-router.sh"
DIAG="$SCRIPT_DIR/diagnose-router.sh"
HERMES_PY="$HERMES_HOME/hermes-agent/venv/bin/python"
[[ -x "$HERMES_PY" ]] || HERMES_PY="$(command -v python3 || true)"
[[ -n "$HERMES_PY" ]] || { echo "Python not found" >&2; exit 1; }
[[ -f "$PATCH" ]] || { echo "Missing $PATCH" >&2; exit 1; }
[[ -f "$SMART" ]] || { echo "Missing $SMART" >&2; exit 1; }
[[ -f "$DIAG" ]] || { echo "Missing $DIAG" >&2; exit 1; }

echo "=== Hermes Smart Router backport ==="
echo "home=$HERMES_HOME"
echo "python=$HERMES_PY"
echo

# Stop only the gateway while Python source is patched. The LLM runtime stays warm.
systemctl --user stop hermes-gateway.service 2>/dev/null || true

rollback_gateway() {
  systemctl --user restart hermes-gateway.service 2>/dev/null || true
}
trap rollback_gateway EXIT

"$HERMES_PY" "$PATCH"

# Apply the config + router skill after the implementation understands defer.
bash "$SMART"

# smart-router restarts the gateway itself; make the trap harmless.
trap - EXIT

# Explicit final validation. Do not run an LLM inference here — this script must stay quick.
echo
echo "=== Final router diagnostic ==="
bash "$DIAG"

echo
echo "Backport complete. If ROUTER_STATUS is SUPPORTED/ACTIVE and schema bytes dropped, test with:"
echo "  time timeout 180s hermes -z 'Responda somente: Brasília'"
