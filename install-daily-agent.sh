#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
SYSTEMD_USER="$HOME/.config/systemd/user"
ENV_DIR="$HOME/.config/hermes"
ENV_FILE="$ENV_DIR/daily-agent.env"
SERVICE="$SYSTEMD_USER/hermes-daily-agent.service"
PORT="${HERMES_DAILY_AGENT_PORT:-8087}"
MODEL_REF="${HERMES_DAILY_AGENT_HF:-Qwen/Qwen3-0.6B-GGUF:Q4_0}"
MODEL_NAME="${HERMES_DAILY_AGENT_MODEL:-Qwen3-0.6B-Q4_0.gguf}"
THREADS="${HERMES_DAILY_AGENT_THREADS:-2}"
CTX="${HERMES_DAILY_AGENT_CTX:-2048}"

log() { printf '[daily-agent] %s\n' "$*"; }

find_llama_server() {
  local candidate exec_line
  for candidate in \
    "$(command -v llama-server 2>/dev/null || true)" \
    "$HERMES_HOME/llama.cpp/build/bin/llama-server" \
    "$HOME/llama.cpp/build/bin/llama-server" \
    "/usr/local/bin/llama-server" \
    "/usr/bin/llama-server"; do
    [ -n "$candidate" ] && [ -x "$candidate" ] && { printf '%s\n' "$candidate"; return 0; }
  done

  exec_line="$(systemctl --user cat hermes-local-llm.service 2>/dev/null | sed -n 's/^ExecStart=//p' | head -n1 || true)"
  if [ -n "$exec_line" ]; then
    candidate="$(printf '%s\n' "$exec_line" | awk '{print $1}')"
    [ -x "$candidate" ] && { printf '%s\n' "$candidate"; return 0; }
  fi
  return 1
}

LLAMA_SERVER="$(find_llama_server || true)"
if [ -z "$LLAMA_SERVER" ]; then
  log "ERRO: não encontrei o llama-server já usado pelo Hermes."
  log "Rode: systemctl --user cat hermes-local-llm.service | grep ExecStart"
  exit 2
fi

mkdir -p "$SYSTEMD_USER" "$ENV_DIR" "$HERMES_HOME/core-v2/state"

cat > "$ENV_FILE" <<EOF
# Hermes Daily Agent - somente local
HERMES_DAILY_AGENT_BASE_URL=http://127.0.0.1:${PORT}/v1
HERMES_DAILY_AGENT_MODEL=${MODEL_NAME}
HERMES_DAILY_AGENT_TIMEOUT=3.5
EOF
chmod 600 "$ENV_FILE"

cat > "$SERVICE" <<EOF
[Unit]
Description=Hermes Daily Agent - Qwen3 0.6B local semantic brain
After=network-online.target

[Service]
Type=simple
ExecStart=${LLAMA_SERVER} -hf ${MODEL_REF} --host 127.0.0.1 --port ${PORT} -c ${CTX} -t ${THREADS} -np 1
Restart=always
RestartSec=3
Environment=HOME=${HOME}
Environment=HF_HOME=${HERMES_HOME}/models/huggingface

[Install]
WantedBy=default.target
EOF

# Estado antigo do circuit breaker não deve bloquear o novo modelo dedicado.
rm -f "$HERMES_HOME/core-v2/state/daily_agent_health.json"

systemctl --user daemon-reload
systemctl --user enable --now hermes-daily-agent.service
systemctl --user restart hermes-daily-agent.service

log "Modelo diário: ${MODEL_REF}"
log "Endpoint local: http://127.0.0.1:${PORT}/v1"
log "A primeira inicialização pode demorar enquanto o GGUF (~430 MB) é baixado."

for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    log "Daily Agent pronto."
    exit 0
  fi
  if ! systemctl --user is-active --quiet hermes-daily-agent.service; then
    log "ERRO: serviço parou durante a inicialização."
    journalctl --user -u hermes-daily-agent.service -n 40 --no-pager || true
    exit 3
  fi
  sleep 2
done

log "ERRO: Daily Agent não ficou saudável dentro do tempo esperado."
journalctl --user -u hermes-daily-agent.service -n 40 --no-pager || true
exit 4
