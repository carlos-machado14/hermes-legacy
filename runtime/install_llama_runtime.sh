#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Run this as the Hermes user, not root. The script uses sudo only for missing build packages." >&2
  exit 1
fi

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
RUNTIME_ROOT="${HERMES_LOCAL_RUNTIME_ROOT:-$HERMES_HOME/local-runtime}"
LLAMA_SRC="$RUNTIME_ROOT/llama.cpp"
MODEL_DIR="${HERMES_LOCAL_MODEL_DIR:-$HERMES_HOME/models}"
MODEL_FILE="${HERMES_LOCAL_MODEL_FILE:-Qwen3-4B-Q4_K_M.gguf}"
MODEL_PATH="$MODEL_DIR/$MODEL_FILE"
MODEL_URL="${HERMES_LOCAL_MODEL_URL:-https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf?download=true}"
MODEL_SHA256="${HERMES_LOCAL_MODEL_SHA256:-7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5}"
PORT="${HERMES_LOCAL_PORT:-8088}"
CONTEXT="${HERMES_LOCAL_CONTEXT:-32768}"
THREADS="${HERMES_LOCAL_THREADS:-$(nproc 2>/dev/null || echo 4)}"
BUILD_JOBS="${HERMES_LOCAL_BUILD_JOBS:-$THREADS}"
SYSTEMD_DIR="$HOME/.config/systemd/user"
SERVICE="$SYSTEMD_DIR/hermes-local-llm.service"

log() { printf '\n[hermes-local-runtime] %s\n' "$*"; }
die() { printf '\n[hermes-local-runtime] ERROR: %s\n' "$*" >&2; exit 1; }

mkdir -p "$RUNTIME_ROOT" "$MODEL_DIR" "$SYSTEMD_DIR"

missing=()
for cmd in git cmake c++ curl sha256sum; do
  command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
done
if (( ${#missing[@]} )); then
  log "Installing build dependencies: ${missing[*]}"
  command -v sudo >/dev/null 2>&1 || die "Missing build tools and sudo is not available."
  sudo apt-get update
  sudo apt-get install -y build-essential cmake git curl ca-certificates
fi

if [[ ! -d "$LLAMA_SRC/.git" ]]; then
  log "Cloning llama.cpp into Hermes runtime..."
  git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$LLAMA_SRC"
else
  log "Updating existing llama.cpp checkout..."
  git -C "$LLAMA_SRC" pull --ff-only || true
fi

log "Building llama-server (CPU native)..."
cmake -S "$LLAMA_SRC" -B "$LLAMA_SRC/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_NATIVE=ON \
  -DLLAMA_CURL=OFF
cmake --build "$LLAMA_SRC/build" --config Release -j "$BUILD_JOBS" --target llama-server

LLAMA_SERVER="$LLAMA_SRC/build/bin/llama-server"
[[ -x "$LLAMA_SERVER" ]] || die "llama-server build not found at $LLAMA_SERVER"

need_download=1
if [[ -f "$MODEL_PATH" ]]; then
  current="$(sha256sum "$MODEL_PATH" | awk '{print $1}')"
  if [[ "$current" == "$MODEL_SHA256" ]]; then
    need_download=0
    log "Model already present and checksum is valid."
  else
    log "Existing model checksum differs; moving it aside."
    mv "$MODEL_PATH" "$MODEL_PATH.invalid.$(date +%Y%m%d-%H%M%S)"
  fi
fi

if [[ "$need_download" -eq 1 ]]; then
  log "Downloading $MODEL_FILE (~2.5 GB) into Hermes model store..."
  curl -L --fail --retry 5 --retry-delay 3 --continue-at - \
    -o "$MODEL_PATH.part" "$MODEL_URL"
  mv "$MODEL_PATH.part" "$MODEL_PATH"
fi

log "Verifying model checksum..."
echo "$MODEL_SHA256  $MODEL_PATH" | sha256sum -c -

cat > "$SERVICE" <<EOF
[Unit]
Description=Hermes Local LLM Runtime (llama.cpp)
After=network-online.target

[Service]
Type=simple
ExecStart=$LLAMA_SERVER --model $MODEL_PATH --host 127.0.0.1 --port $PORT --ctx-size $CONTEXT --parallel 1 --threads $THREADS --jinja
Restart=always
RestartSec=5
TimeoutStopSec=30
Nice=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now hermes-local-llm.service

log "Waiting for the local OpenAI-compatible endpoint..."
ready=0
for _ in $(seq 1 90); do
  if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
[[ "$ready" -eq 1 ]] || {
  systemctl --user --no-pager --full status hermes-local-llm.service || true
  journalctl --user -u hermes-local-llm.service -n 80 --no-pager || true
  die "Local model service did not become ready."
}

MODEL_ID="$(curl -fsS "http://127.0.0.1:$PORT/v1/models" | python3 -c '
import json,sys
p=json.load(sys.stdin); rows=p.get("data",[]) if isinstance(p,dict) else []
print((rows[0].get("id") if rows else "") or "")
')"
[[ -n "$MODEL_ID" ]] || MODEL_ID="$MODEL_FILE"
printf '%s\n' "$MODEL_ID" > "$RUNTIME_ROOT/model.id"
printf '%s\n' "http://127.0.0.1:$PORT/v1" > "$RUNTIME_ROOT/base_url"
printf '%s\n' "$CONTEXT" > "$RUNTIME_ROOT/context_length"

log "Runtime ready"
echo "service=hermes-local-llm.service"
echo "base_url=http://127.0.0.1:$PORT/v1"
echo "model=$MODEL_ID"
echo "context=$CONTEXT"
