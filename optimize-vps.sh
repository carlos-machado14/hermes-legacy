#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Run optimize-vps.sh as the Hermes user, not root." >&2
  exit 1
fi

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export HERMES_HOME
HERMES_BIN="${HERMES_BIN:-$(command -v hermes || true)}"
[[ -n "$HERMES_BIN" ]] || { echo "Hermes CLI not found" >&2; exit 1; }

# 16k is too small for a full Hermes installation with its normal tool schemas.
# Keep the model's native 32k window and save RAM through quantized KV cache instead.
CONTEXT="${HERMES_FAST_CONTEXT:-32768}"
MIN_CONTEXT="${HERMES_FAST_MIN_CONTEXT:-8192}"
PORT="${HERMES_LOCAL_PORT:-8088}"
THREADS="${HERMES_LOCAL_THREADS:-$(nproc 2>/dev/null || echo 4)}"
BATCH="${HERMES_LOCAL_BATCH:-1024}"
UBATCH="${HERMES_LOCAL_UBATCH:-256}"
CACHE_K="${HERMES_LOCAL_CACHE_K:-q8_0}"
CACHE_V="${HERMES_LOCAL_CACHE_V:-q8_0}"

# Compression profile for a 32k local window. These can still be overridden.
COMPRESSION_THRESHOLD="${HERMES_FAST_COMPRESSION_THRESHOLD:-24000}"
PRUNE_THRESHOLD="${HERMES_FAST_PRUNE_THRESHOLD:-18000}"

RUNTIME_ROOT="$HERMES_HOME/local-runtime"
LLAMA_SERVER="$RUNTIME_ROOT/llama.cpp/build/bin/llama-server"
MODEL_DIR="$HERMES_HOME/models"
MODEL_PATH="${HERMES_LOCAL_MODEL_PATH:-$MODEL_DIR/Qwen3-4B-Q4_K_M.gguf}"
SERVICE="$HOME/.config/systemd/user/hermes-local-llm.service"
DROPIN="$HOME/.config/systemd/user/hermes-gateway.service.d/local-only.conf"
ENV_FILE="$HERMES_HOME/.env"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$HERMES_HOME/backups/vps-optimize-$STAMP"

log(){ printf '\n[hermes-fast] %s\n' "$*"; }
die(){ printf '\n[hermes-fast] ERROR: %s\n' "$*" >&2; exit 1; }

[[ -x "$LLAMA_SERVER" ]] || die "llama-server not found: $LLAMA_SERVER"
[[ -f "$MODEL_PATH" ]] || die "model not found: $MODEL_PATH"
[[ -f "$SERVICE" ]] || die "service not found: $SERVICE"

mkdir -p "$BACKUP"
cp -a "$SERVICE" "$BACKUP/hermes-local-llm.service"
cp -a "$HERMES_HOME/config.yaml" "$BACKUP/config.yaml" 2>/dev/null || true
cp -a "$ENV_FILE" "$BACKUP/.env" 2>/dev/null || true
cp -a "$DROPIN" "$BACKUP/local-only.conf" 2>/dev/null || true
printf 'created_at=%s\ncontext=%s\nmin_context=%s\ncompression_threshold=%s\nprune_threshold=%s\n' \
  "$STAMP" "$CONTEXT" "$MIN_CONTEXT" "$COMPRESSION_THRESHOLD" "$PRUNE_THRESHOLD" > "$BACKUP/metadata.txt"
log "Backup: $BACKUP"

upsert_env(){
  local key="$1" value="$2"
  touch "$ENV_FILE"
  python3 - "$ENV_FILE" "$key" "$value" <<'PY'
import sys
from pathlib import Path
p=Path(sys.argv[1]); key=sys.argv[2]; value=sys.argv[3]
lines=p.read_text(encoding='utf-8').splitlines() if p.exists() else []
out=[]; done=False
for line in lines:
    if line.startswith(key+'='):
        if not done:
            out.append(f'{key}={value}'); done=True
    else:
        out.append(line)
if not done: out.append(f'{key}={value}')
p.write_text('\n'.join(out).rstrip()+'\n', encoding='utf-8')
PY
  chmod 600 "$ENV_FILE" 2>/dev/null || true
}

log "Stopping gateway while the local runtime is retuned"
systemctl --user stop hermes-gateway.service 2>/dev/null || true

log "Writing low-latency llama.cpp profile"
cat > "$SERVICE" <<EOF
[Unit]
Description=Hermes Local LLM Runtime (llama.cpp) - low latency
After=network-online.target

[Service]
Type=simple
ExecStart=$LLAMA_SERVER --model $MODEL_PATH --host 127.0.0.1 --port $PORT --ctx-size $CONTEXT --parallel 1 --threads $THREADS --threads-batch $THREADS --batch-size $BATCH --ubatch-size $UBATCH --cache-type-k $CACHE_K --cache-type-v $CACHE_V --flash-attn auto --cache-prompt --cache-reuse 256 --jinja --reasoning off
Restart=always
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=default.target
EOF

upsert_env HERMES_MIN_CONTEXT_LENGTH "$MIN_CONTEXT"
upsert_env HERMES_API_TIMEOUT 1800
upsert_env HERMES_API_CALL_STALE_TIMEOUT 900
upsert_env HERMES_LOCAL_STREAM_STALE_TIMEOUT 900
upsert_env HERMES_CRON_TIMEOUT 1800

mkdir -p "$(dirname "$DROPIN")"
cat > "$DROPIN" <<EOF
[Unit]
Wants=hermes-local-llm.service
After=hermes-local-llm.service

[Service]
Environment=HERMES_MIN_CONTEXT_LENGTH=$MIN_CONTEXT
Environment=HERMES_API_TIMEOUT=1800
Environment=HERMES_API_CALL_STALE_TIMEOUT=900
Environment=HERMES_LOCAL_STREAM_STALE_TIMEOUT=900
Environment=HERMES_CRON_TIMEOUT=1800
EOF

log "Applying Hermes local-context profile"
"$HERMES_BIN" config set model.context_length "$CONTEXT"
"$HERMES_BIN" config set compression.enabled true >/dev/null 2>&1 || true
"$HERMES_BIN" config set compression.threshold_tokens "$COMPRESSION_THRESHOLD" >/dev/null 2>&1 || true
"$HERMES_BIN" config set compression.proactive_prune_tokens "$PRUNE_THRESHOLD" >/dev/null 2>&1 || true
"$HERMES_BIN" config set compression.proactive_prune_min_reclaim_tokens 2048 >/dev/null 2>&1 || true
"$HERMES_BIN" config set compression.protect_last_n 10 >/dev/null 2>&1 || true
"$HERMES_BIN" config set compression.max_attempts 5 >/dev/null 2>&1 || true
"$HERMES_BIN" config set streaming.enabled true >/dev/null 2>&1 || true

printf '%s\n' "$CONTEXT" > "$RUNTIME_ROOT/context_length"

systemctl --user daemon-reload
systemctl --user restart hermes-local-llm.service

ready=0
for _ in $(seq 1 90); do
  if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 2
done

if [[ "$ready" -ne 1 ]]; then
  echo "Optimized runtime did not become ready; restoring previous service." >&2
  cp -a "$BACKUP/hermes-local-llm.service" "$SERVICE"
  [[ -f "$BACKUP/local-only.conf" ]] && cp -a "$BACKUP/local-only.conf" "$DROPIN"
  [[ -f "$BACKUP/config.yaml" ]] && cp -a "$BACKUP/config.yaml" "$HERMES_HOME/config.yaml"
  [[ -f "$BACKUP/.env" ]] && cp -a "$BACKUP/.env" "$ENV_FILE"
  systemctl --user daemon-reload
  systemctl --user restart hermes-local-llm.service
  systemctl --user restart hermes-gateway.service 2>/dev/null || true
  journalctl --user -u hermes-local-llm.service -n 80 --no-pager || true
  exit 2
fi

log "Restarting Hermes gateway"
systemctl --user restart hermes-gateway.service 2>/dev/null || "$HERMES_BIN" gateway restart || true

log "Smoke test"
MODEL_ID="$(cat "$RUNTIME_ROOT/model.id" 2>/dev/null || basename "$MODEL_PATH")"
PAYLOAD="$(MODEL_ID="$MODEL_ID" python3 - <<'PY'
import json, os
print(json.dumps({
  'model': os.environ['MODEL_ID'],
  'messages': [{'role':'user','content':'Responda somente: OK'}],
  'stream': False,
  'max_tokens': 8,
  'temperature': 0,
}))
PY
)"
START="$(date +%s%3N)"
curl -fsS --max-time 120 -H 'Content-Type: application/json' -d "$PAYLOAD" \
  "http://127.0.0.1:$PORT/v1/chat/completions" >/tmp/hermes-fast-smoke.json
END="$(date +%s%3N)"
ELAPSED=$((END-START))

echo
printf 'context=%s\n' "$CONTEXT"
printf 'minimum_context=%s\n' "$MIN_CONTEXT"
printf 'compression_threshold=%s\n' "$COMPRESSION_THRESHOLD"
printf 'prune_threshold=%s\n' "$PRUNE_THRESHOLD"
printf 'kv_cache=%s/%s\n' "$CACHE_K" "$CACHE_V"
printf 'thinking_default=off\n'
printf 'streaming=enabled\n'
printf 'smoke_test_ms=%s\n' "$ELAPSED"
echo
systemctl --user --no-pager status hermes-local-llm.service | sed -n '1,12p' || true
echo
free -h || true

echo "Optimization complete. Backup: $BACKUP"
