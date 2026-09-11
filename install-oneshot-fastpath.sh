#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Run install-oneshot-fastpath.sh as the Hermes user, not root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export HERMES_HOME
HERMES_BIN="${HERMES_BIN:-$(command -v hermes || true)}"
[[ -n "$HERMES_BIN" ]] || { echo "Hermes CLI not found" >&2; exit 1; }
[[ -f "$SCRIPT_DIR/patches/apply_oneshot_fastpath.py" ]] || { echo "Missing patch script" >&2; exit 1; }

# First publish the latest router implementation (v4 exposes /v1/route).
bash "$SCRIPT_DIR/install-fast-router.sh"

health="$(curl -fsS --max-time 2 http://127.0.0.1:8089/health)"
echo "router_health=$health"
if ! grep -q '"router_version": 4' <<<"$health"; then
  echo "Fast router v4 is required before patching oneshot." >&2
  exit 2
fi

python3 "$SCRIPT_DIR/patches/apply_oneshot_fastpath.py"

# No llama.cpp restart is needed. Restart gateway only so long-lived surfaces pick
# up any refreshed config/service relationship; CLI -z uses the patched file immediately.
systemctl --user restart hermes-gateway.service 2>/dev/null || "$HERMES_BIN" gateway restart || true

echo
echo "=== Hermes oneshot pre-agent fast path installed ==="
echo "DIRECT requests now route before AIAgent construction."
echo "AGENT/tool requests still fall through to the full Hermes stack."
echo
echo "Route probes:"
curl -fsS -H 'Content-Type: application/json' -d '{"text":"Qual a capital do Brasil?"}' http://127.0.0.1:8089/v1/route; echo
curl -fsS -H 'Content-Type: application/json' -d '{"text":"Qual o dólar hoje?"}' http://127.0.0.1:8089/v1/route; echo

echo
echo "Test twice:"
echo "  time timeout 15s hermes -z 'Responda somente: Brasília'"
echo "  time timeout 15s hermes -z 'Responda somente: Brasília'"
echo
echo "Then confirm an agent request still routes through Hermes:"
echo "  time timeout 90s hermes -z 'Use uma ferramenta para descobrir o hostname desta máquina e responda somente com ele.'"
