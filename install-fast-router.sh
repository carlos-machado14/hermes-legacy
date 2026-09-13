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

BASE_SRC="$SCRIPT_DIR/runtime/hermes_fast_router.py"
V7_SRC="$SCRIPT_DIR/runtime/hermes_fast_router_v7.py"
V8_SRC="$SCRIPT_DIR/runtime/hermes_fast_router_v8.py"
ONESHOT_V2="$SCRIPT_DIR/patches/apply_oneshot_fastpath_v2.py"
[[ -f "$BASE_SRC" ]] || { echo "Missing $BASE_SRC" >&2; exit 1; }
[[ -f "$V7_SRC" ]] || { echo "Missing $V7_SRC" >&2; exit 1; }
[[ -f "$V8_SRC" ]] || { echo "Missing $V8_SRC" >&2; exit 1; }
[[ -f "$ONESHOT_V2" ]] || { echo "Missing $ONESHOT_V2" >&2; exit 1; }

RUNTIME_DIR="$HERMES_HOME/local-runtime/fast-router"
BASE_PY="$RUNTIME_DIR/hermes_fast_router.py"
V7_PY="$RUNTIME_DIR/hermes_fast_router_v7.py"
ROUTER_PY="$RUNTIME_DIR/hermes_fast_router_v8.py"
SERVICE="$HOME/.config/systemd/user/hermes-fast-router.service"
GATEWAY_DROPIN="$HOME/.config/systemd/user/hermes-gateway.service.d/local-only.conf"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$HERMES_HOME/backups/fast-router-$STAMP"
mkdir -p "$BACKUP" "$RUNTIME_DIR" "$(dirname "$SERVICE")" "$(dirname "$GATEWAY_DROPIN")"

cp -a "$HERMES_HOME/config.yaml" "$BACKUP/config.yaml" 2>/dev/null || true
cp -a "$SERVICE" "$BACKUP/hermes-fast-router.service" 2>/dev/null || true
cp -a "$GATEWAY_DROPIN" "$BACKUP/local-only.conf" 2>/dev/null || true
cp -a "$BASE_SRC" "$BASE_PY"
cp -a "$V7_SRC" "$V7_PY"
cp -a "$V8_SRC" "$ROUTER_PY"
chmod 700 "$BASE_PY" "$V7_PY" "$ROUTER_PY"

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

"$HERMES_BIN" config set model.provider custom >/dev/null
"$HERMES_BIN" config set model.base_url http://127.0.0.1:8089/v1 >/dev/null

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
health=""
for _ in $(seq 1 30); do
  health="$(curl -fsS --max-time 2 http://127.0.0.1:8089/health 2>/dev/null || true)"
  if grep -q '"router_version": 8' <<<"$health"; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" -ne 1 ]]; then
  echo "Fast router v8 did not become ready. Restoring config." >&2
  [[ -f "$BACKUP/config.yaml" ]] && cp -a "$BACKUP/config.yaml" "$HERMES_HOME/config.yaml"
  systemctl --user disable --now hermes-fast-router.service >/dev/null 2>&1 || true
  systemctl --user daemon-reload
  journalctl --user -u hermes-fast-router.service -n 100 --no-pager || true
  exit 2
fi

python3 "$ONESHOT_V2"
systemctl --user restart hermes-gateway.service 2>/dev/null || "$HERMES_BIN" gateway restart || true

echo "=== Fast router v8 installed ==="
printf 'model.base_url='; "$HERMES_BIN" config get model.base_url || true
echo "router=http://127.0.0.1:8089/v1"
echo "backend=http://127.0.0.1:8088/v1"
echo "backup=$BACKUP"
echo "health=$health"
echo
echo "Cron Telegram fastpath enabled."
echo "Examples:"
echo "  crie uma rotina todo dia às 8h para me mandar notícias de Flutter"
echo "  quais rotinas eu tenho?"
echo "  pause a rotina <nome>"
