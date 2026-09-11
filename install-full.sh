#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Run ./install-full.sh as the Hermes user (for you: carlos), not with sudo." >&2
  echo "The script will ask for sudo only if build packages are missing." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export HERMES_HOME
HERMES_BIN="${HERMES_BIN:-$(command -v hermes || true)}"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$HERMES_HOME/backups/full-local-only-$STAMP"
ENV_FILE="$HERMES_HOME/.env"

log()  { printf '\n\033[1;36m[hermes-local]\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33m[hermes-local]\033[0m %s\n' "$*" >&2; }
die()  { printf '\n\033[1;31m[hermes-local]\033[0m %s\n' "$*" >&2; exit 1; }

[[ -n "$HERMES_BIN" && -x "$HERMES_BIN" ]] || die "Hermes CLI not found in PATH."
[[ -d "$HERMES_HOME/hermes-agent" ]] || die "Existing Hermes install not found at $HERMES_HOME/hermes-agent"

log "Existing Hermes installation"
"$HERMES_BIN" --version || true
echo "HERMES_HOME=$HERMES_HOME"

log "Creating pre-migration backup"
mkdir -p "$BACKUP_DIR"
for rel in config.yaml .env auth.json cron/jobs.json SOUL.md; do
  src="$HERMES_HOME/$rel"
  if [[ -e "$src" ]]; then
    mkdir -p "$BACKUP_DIR/$(dirname "$rel")"
    cp -a "$src" "$BACKUP_DIR/$rel"
  fi
done
if [[ -f "$HERMES_HOME/hermes-agent/agent/model_metadata.py" ]]; then
  mkdir -p "$BACKUP_DIR/hermes-source"
  cp -a "$HERMES_HOME/hermes-agent/agent/model_metadata.py" "$BACKUP_DIR/hermes-source/model_metadata.py"
fi
if [[ -f "$HOME/.config/systemd/user/hermes-gateway.service" ]]; then
  mkdir -p "$BACKUP_DIR/systemd"
  cp -a "$HOME/.config/systemd/user/hermes-gateway.service" "$BACKUP_DIR/systemd/hermes-gateway.service"
fi
if [[ -d "$HOME/.config/systemd/user/hermes-gateway.service.d" ]]; then
  mkdir -p "$BACKUP_DIR/systemd/hermes-gateway.service.d"
  cp -a "$HOME/.config/systemd/user/hermes-gateway.service.d/." "$BACKUP_DIR/systemd/hermes-gateway.service.d/"
fi
printf 'created_at=%s\nhermes_home=%s\n' "$STAMP" "$HERMES_HOME" > "$BACKUP_DIR/metadata.txt"
chmod -R u+rwX,go-rwx "$BACKUP_DIR" 2>/dev/null || true

echo "backup=$BACKUP_DIR"

log "Patching the upstream 64k hard floor for our local distribution"
python3 "$SCRIPT_DIR/patches/apply_local_context.py"

log "Installing Hermes-managed local model runtime"
bash "$SCRIPT_DIR/runtime/install_llama_runtime.sh"

RUNTIME_ROOT="$HERMES_HOME/local-runtime"
MODEL_ID="$(cat "$RUNTIME_ROOT/model.id" 2>/dev/null || true)"
BASE_URL="$(cat "$RUNTIME_ROOT/base_url" 2>/dev/null || true)"
CONTEXT="$(cat "$RUNTIME_ROOT/context_length" 2>/dev/null || true)"
[[ -n "$MODEL_ID" ]] || die "Runtime did not publish model.id"
[[ -n "$BASE_URL" ]] || die "Runtime did not publish base_url"
[[ -n "$CONTEXT" ]] || CONTEXT=32768

log "Bootstrapping Obsidian-compatible knowledge vault"
bash "$SCRIPT_DIR/vault/bootstrap_vault.sh"

upsert_env() {
  local key="$1" value="$2"
  touch "$ENV_FILE"
  chmod 600 "$ENV_FILE" 2>/dev/null || true
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
if not done:
    out.append(f'{key}={value}')
p.write_text('\n'.join(out).rstrip()+'\n',encoding='utf-8')
PY
}

# These are non-secret local runtime controls. Existing provider credentials remain untouched
# because web/voice/other integrations may still need their own keys.
upsert_env HERMES_MIN_CONTEXT_LENGTH 16384
upsert_env HERMES_API_TIMEOUT 1800
upsert_env HERMES_API_CALL_STALE_TIMEOUT 900
upsert_env HERMES_LOCAL_STREAM_STALE_TIMEOUT 900
upsert_env HERMES_CRON_TIMEOUT 1800

log "Configuring Hermes to use only the managed local model for inference"
"$HERMES_BIN" config set model.provider custom
"$HERMES_BIN" config set model.base_url "$BASE_URL"
"$HERMES_BIN" config set model.default "$MODEL_ID"
"$HERMES_BIN" config set model.context_length "$CONTEXT"

"$HERMES_BIN" fallback clear >/dev/null 2>&1 || true
"$HERMES_BIN" config unset fallback_model >/dev/null 2>&1 || true
"$HERMES_BIN" config unset fallback_providers >/dev/null 2>&1 || true
"$HERMES_BIN" config unset model.api_key >/dev/null 2>&1 || true

# Cron fleet defaults.
"$HERMES_BIN" config set cron.model_provider custom >/dev/null
"$HERMES_BIN" config set cron.model "$MODEL_ID" >/dev/null

# Delegated agents must serialize on a small VPS instead of spawning 10 local generations.
"$HERMES_BIN" config set delegation.provider custom >/dev/null 2>&1 || true
"$HERMES_BIN" config set delegation.model "$MODEL_ID" >/dev/null 2>&1 || true
"$HERMES_BIN" config set delegation.max_concurrent_children 1 >/dev/null 2>&1 || true

# Auxiliary text tasks stay on the same local model.
for task in compression title_generation; do
  "$HERMES_BIN" config set "auxiliary.$task.provider" main >/dev/null 2>&1 || true
  "$HERMES_BIN" config unset "auxiliary.$task.model" >/dev/null 2>&1 || true
  "$HERMES_BIN" config unset "auxiliary.$task.base_url" >/dev/null 2>&1 || true
  "$HERMES_BIN" config unset "auxiliary.$task.api_key" >/dev/null 2>&1 || true
done

# Small-context profile: prune tool output early and compact before the 32k window gets crowded.
"$HERMES_BIN" config set compression.enabled true >/dev/null 2>&1 || true
"$HERMES_BIN" config set compression.threshold_tokens 18000 >/dev/null 2>&1 || true
"$HERMES_BIN" config set compression.proactive_prune_tokens 12000 >/dev/null 2>&1 || true
"$HERMES_BIN" config set compression.proactive_prune_min_reclaim_tokens 2048 >/dev/null 2>&1 || true
"$HERMES_BIN" config set compression.protect_last_n 12 >/dev/null 2>&1 || true
"$HERMES_BIN" config set compression.max_attempts 5 >/dev/null 2>&1 || true

log "Migrating explicit provider/model pins on existing cron jobs"
JOBS_FILE="$HERMES_HOME/cron/jobs.json"
if [[ -f "$JOBS_FILE" ]]; then
  mapfile -t JOB_IDS < <(JOBS_FILE="$JOBS_FILE" python3 - <<'PY'
import json, os
p=os.environ['JOBS_FILE']
try:
    data=json.load(open(p,encoding='utf-8'))
except Exception:
    raise SystemExit(0)
seen=set()
def walk(node):
    if isinstance(node,dict):
        # Current Hermes jobs use `id`; older builds/plugins may use `job_id`.
        jid=node.get('id') or node.get('job_id')
        # Avoid treating arbitrary nested objects with an id as cron jobs.
        looks_like_job = bool(node.get('schedule') or node.get('prompt') or node.get('name'))
        if jid and looks_like_job and jid not in seen:
            seen.add(jid); print(jid)
        for value in node.values(): walk(value)
    elif isinstance(node,list):
        for value in node: walk(value)
walk(data)
PY
)
  migrated=0
  for job_id in "${JOB_IDS[@]}"; do
    if "$HERMES_BIN" cron edit "$job_id" --provider custom --model "$MODEL_ID" >/dev/null 2>&1; then
      migrated=$((migrated + 1))
    else
      warn "Could not repin cron job $job_id automatically; fleet default is already local."
    fi
  done
  echo "cron_jobs_repinned=$migrated"
else
  echo "cron_jobs_repinned=0"
fi

log "Making Hermes gateway depend on its own local model service"
DROPIN="$HOME/.config/systemd/user/hermes-gateway.service.d"
mkdir -p "$DROPIN"
cat > "$DROPIN/local-only.conf" <<EOF
[Unit]
Wants=hermes-local-llm.service
After=hermes-local-llm.service

[Service]
Environment=HERMES_MIN_CONTEXT_LENGTH=16384
Environment=HERMES_API_TIMEOUT=1800
Environment=HERMES_API_CALL_STALE_TIMEOUT=900
Environment=HERMES_LOCAL_STREAM_STALE_TIMEOUT=900
Environment=HERMES_CRON_TIMEOUT=1800
EOF
systemctl --user daemon-reload
systemctl --user enable hermes-local-llm.service >/dev/null 2>&1 || true
systemctl --user restart hermes-local-llm.service

for _ in $(seq 1 90); do
  curl -fsS --max-time 2 "${BASE_URL%/}/models" >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS --max-time 3 "${BASE_URL%/}/models" >/dev/null || die "Local model endpoint is not ready; gateway was not restarted."

systemctl --user restart hermes-gateway.service || "$HERMES_BIN" gateway restart || true

log "Direct local inference smoke test"
PAYLOAD="$(MODEL_ID="$MODEL_ID" python3 - <<'PY'
import json,os
print(json.dumps({
  'model': os.environ['MODEL_ID'],
  'messages':[{'role':'user','content':'Responda somente: OK'}],
  'stream':False,
  'max_tokens':16,
  'temperature':0
}))
PY
)"
curl -fsS --max-time 900 -H 'Content-Type: application/json' \
  -d "$PAYLOAD" "${BASE_URL%/}/chat/completions" > /tmp/hermes-local-direct-test.json \
  || die "Local /chat/completions smoke test failed. See: journalctl --user -u hermes-local-llm.service -n 100"

log "Effective configuration"
printf 'provider='; "$HERMES_BIN" config get model.provider || true
printf 'model='; "$HERMES_BIN" config get model.default || true
printf 'base_url='; "$HERMES_BIN" config get model.base_url || true
printf 'context='; "$HERMES_BIN" config get model.context_length || true
printf 'cron_provider='; "$HERMES_BIN" config get cron.model_provider || true
printf 'cron_model='; "$HERMES_BIN" config get cron.model || true
printf 'vault='; grep '^OBSIDIAN_VAULT_PATH=' "$ENV_FILE" | cut -d= -f2- || true

cat <<EOF

============================================================
HERMES LOCAL STACK INSTALLED
============================================================
Hermes       : existing installation preserved
LLM runtime  : hermes-local-llm.service (llama.cpp)
Model        : $MODEL_ID
Endpoint     : $BASE_URL
Context      : $CONTEXT
Min context  : 16384 (custom patch)
Fallback LLM : disabled
Cron         : local model
Delegation   : local, concurrency 1
Knowledge    : $HERMES_HOME/vault (Obsidian-compatible)
Backup       : $BACKUP_DIR

Next:
  ./verify.sh
============================================================
EOF
