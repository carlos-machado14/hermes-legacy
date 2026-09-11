#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Run install-fast-router.sh as the Hermes user, not root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export HERMES_HOME
HERMES_BIN="${HERMES_BIN:-$(command -v hermes || true)}"
[[ -n "$HERMES_BIN" ]] || { echo "Hermes CLI not found" >&2; exit 1; }

SRC="$SCRIPT_DIR/runtime/hermes_fast_router.py"
[[ -f "$SRC" ]] || { echo "Missing $SRC" >&2; exit 1; }

RUNTIME_DIR="$HERMES_HOME/local-runtime/fast-router"
ROUTER_PY="$RUNTIME_DIR/hermes_fast_router.py"
SERVICE="$HOME/.config/systemd/user/hermes-fast-router.service"
GATEWAY_DROPIN="$HOME/.config/systemd/user/hermes-gateway.service.d/local-only.conf"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$HERMES_HOME/backups/fast-router-$STAMP"
mkdir -p "$BACKUP" "$RUNTIME_DIR" "$(dirname "$SERVICE")" "$(dirname "$GATEWAY_DROPIN")"

cp -a "$HERMES_HOME/config.yaml" "$BACKUP/config.yaml" 2>/dev/null || true
cp -a "$SERVICE" "$BACKUP/hermes-fast-router.service" 2>/dev/null || true
cp -a "$GATEWAY_DROPIN" "$BACKUP/local-only.conf" 2>/dev/null || true
cp -a "$SRC" "$ROUTER_PY"
chmod 700 "$ROUTER_PY"

cat > "$SERVICE" <<EOF
[Unit]
Description=Hermes Local Fast Router
Wants=hermes-local-llm.service
After=hermes-local-llm.service

[Service]
Type=simple
Environment=HERMES_FAST_ROUTER_HOST=127.0.0.1
Environment=HERMES_FAST_ROUTER_PORT=8089
Environment=HERMES_FAST_ROUTER_BACKEND=http://127.0.0.1:8088
Environment=HERMES_FAST_ROUTER_TIMEOUT=1800
ExecStart=/usr/bin/python3 $ROUTER_PY
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
EOF

# Keep all inference local. Hermes now talks to the smart proxy; the proxy talks to llama.cpp.
"$HERMES_BIN" config set model.provider custom >/dev/null
"$HERMES_BIN" config set model.base_url http://127.0.0.1:8089/v1 >/dev/null

# Ensure gateway starts after both local components. Preserve the existing local-context env controls.
cat > "$GATEWAY_DROPIN" <<'EOF'
[Unit]
Wants=hermes-local-llm.service hermes-fast-router.service
After=hermes-local-llm.service hermes-fast-router.service

[Service]
Environment=HERMES_MIN_CONTEXT_LENGTH=8192
Environment=HERMES_API_TIMEOUT=1800
Environment=HERMES_API_CALL_STALE_TIMEOUT=900
Environment=HERMES_LOCAL_STREAM_STALE_TIMEOUT=900
Environment=HERMES_CRON_TIMEOUT=1800
EOF

systemctl --user daemon-reload
systemctl --user enable hermes-fast-router.service >/dev/null
systemctl --user restart hermes-fast-router.service

ready=0
for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 http://127.0.0.1:8089/health >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" -ne 1 ]]; then
  echo "Fast router did not become ready. Restoring config." >&2
  [[ -f "$BACKUP/config.yaml" ]] && cp -a "$BACKUP/config.yaml" "$HERMES_HOME/config.yaml"
  systemctl --user disable --now hermes-fast-router.service >/dev/null 2>&1 || true
  systemctl --user daemon-reload
  journalctl --user -u hermes-fast-router.service -n 100 --no-pager || true
  exit 2
fi

systemctl --user restart hermes-gateway.service 2>/dev/null || "$HERMES_BIN" gateway restart || true

echo "=== Fast router installed ==="
printf 'model.base_url='; "$HERMES_BIN" config get model.base_url || true
echo "router=http://127.0.0.1:8089/v1"
echo "backend=http://127.0.0.1:8088/v1"
echo "backup=$BACKUP"
echo
systemctl --user --no-pager status hermes-fast-router.service | sed -n '1,12p' || true
echo
echo "Test in another terminal:"
echo "  journalctl --user -u hermes-fast-router.service -f"
echo "  time timeout 60s hermes -z 'Responda somente: Brasília'"
