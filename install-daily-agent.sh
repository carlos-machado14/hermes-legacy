#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
SYSTEMD_USER="$HOME/.config/systemd/user"
ENV_DIR="$HOME/.config/hermes"
ENV_FILE="$ENV_DIR/daily-agent.env"
SERVICE="$SYSTEMD_USER/hermes-daily-agent.service"
MODEL_DIR="$HERMES_HOME/models/daily-agent"
MODEL_NAME="${HERMES_DAILY_AGENT_MODEL:-Qwen3-0.6B-Q4_0.gguf}"
MODEL_FILE="$MODEL_DIR/$MODEL_NAME"
MODEL_URL="${HERMES_DAILY_AGENT_MODEL_URL:-https://huggingface.co/ggml-org/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q4_0.gguf?download=true}"
PORT="${HERMES_DAILY_AGENT_PORT:-8087}"
THREADS="${HERMES_DAILY_AGENT_THREADS:-4}"
CTX="${HERMES_DAILY_AGENT_CTX:-1536}"
TIMEOUT="${HERMES_DAILY_AGENT_TIMEOUT:-10.0}"

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

port_free() {
  python3 - "$1" <<'PY'
import socket, sys
port = int(sys.argv[1])
s = socket.socket()
try:
    s.bind(('127.0.0.1', port))
except OSError:
    raise SystemExit(1)
finally:
    s.close()
PY
}

choose_port() {
  local requested="$1" candidate
  if port_free "$requested"; then
    printf '%s\n' "$requested"
    return 0
  fi
  for candidate in 8087 8088 8089 8092 8093 8094 8095 8096 8097 8098 8099; do
    if port_free "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

LLAMA_SERVER="$(find_llama_server || true)"
if [ -z "$LLAMA_SERVER" ]; then
  log "ERRO: não encontrei o llama-server já usado pelo Hermes."
  log "Rode: systemctl --user cat hermes-local-llm.service | grep ExecStart"
  exit 2
fi

# Qwen3 entra em modo de reasoning por padrão em vários templates do llama.cpp.
# Para o classificador diário isso é desperdício e, com saída curta, fazia a API
# devolver somente '<think>'. Detectamos os flags suportados pelo binário instalado
# e desligamos reasoning no próprio servidor. Isso continua 100% local.
HELP="$($LLAMA_SERVER --help 2>&1 || true)"
REASONING_ARGS=""
if printf '%s' "$HELP" | grep -q -- '--reasoning-budget'; then
  REASONING_ARGS="$REASONING_ARGS --reasoning-budget 0"
fi
if printf '%s' "$HELP" | grep -q -- '--reasoning '; then
  REASONING_ARGS="$REASONING_ARGS --reasoning off"
elif printf '%s' "$HELP" | grep -q -- '-rea,'; then
  REASONING_ARGS="$REASONING_ARGS -rea off"
fi
if [ -z "$REASONING_ARGS" ]; then
  log "AVISO: este llama-server não expõe flags de reasoning; /no_think ficará como fallback."
else
  log "Reasoning do Daily Agent será desativado:${REASONING_ARGS}"
fi

mkdir -p "$SYSTEMD_USER" "$ENV_DIR" "$HERMES_HOME/core-v2/state" "$MODEL_DIR"

if [ -s "$MODEL_FILE" ]; then
  SIZE="$(stat -c%s "$MODEL_FILE" 2>/dev/null || echo 0)"
  if [ "$SIZE" -lt 100000000 ]; then
    log "Arquivo de modelo existente é inválido/incompleto (${SIZE} bytes); removendo."
    rm -f "$MODEL_FILE"
  fi
fi

if [ ! -s "$MODEL_FILE" ]; then
  command -v curl >/dev/null 2>&1 || { log "ERRO: curl não encontrado para baixar o GGUF."; exit 5; }
  log "Baixando modelo local (~430 MB) para $MODEL_FILE ..."
  TMP="$MODEL_FILE.part"
  rm -f "$TMP"
  if ! curl -fL --retry 4 --retry-all-errors --retry-delay 2 --connect-timeout 15 -o "$TMP" "$MODEL_URL"; then
    rm -f "$TMP"
    log "ERRO: não consegui baixar o GGUF. Nenhum provider remoto foi ativado."
    exit 6
  fi
  SIZE="$(stat -c%s "$TMP" 2>/dev/null || echo 0)"
  if [ "$SIZE" -lt 100000000 ]; then
    rm -f "$TMP"
    log "ERRO: download retornou somente ${SIZE} bytes; recusando arquivo inválido."
    exit 8
  fi
  mv "$TMP" "$MODEL_FILE"
  log "Download concluído: $((SIZE / 1024 / 1024)) MB."
fi

systemctl --user stop hermes-daily-agent.service 2>/dev/null || true
PORT="$(choose_port "$PORT" || true)"
if [ -z "$PORT" ]; then
  log "ERRO: não encontrei porta local livre para o Daily Agent."
  exit 7
fi

cat > "$ENV_FILE" <<EOF
# Hermes Daily Agent - somente local
HERMES_DAILY_AGENT_BASE_URL=http://127.0.0.1:${PORT}/v1
HERMES_DAILY_AGENT_MODEL=${MODEL_NAME}
HERMES_DAILY_AGENT_TIMEOUT=${TIMEOUT}
EOF
chmod 600 "$ENV_FILE"

cat > "$SERVICE" <<EOF
[Unit]
Description=Hermes Daily Agent - Qwen3 0.6B local semantic brain
After=network-online.target

[Service]
Type=simple
ExecStart=${LLAMA_SERVER} -m ${MODEL_FILE} --host 127.0.0.1 --port ${PORT} -c ${CTX} -t ${THREADS} -np 1${REASONING_ARGS}
Restart=always
RestartSec=3
Environment=HOME=${HOME}

[Install]
WantedBy=default.target
EOF

rm -f "$HERMES_HOME/core-v2/state/daily_agent_health.json"

systemctl --user daemon-reload
systemctl --user enable hermes-daily-agent.service >/dev/null
systemctl --user restart hermes-daily-agent.service

log "Modelo diário local: ${MODEL_FILE}"
log "Endpoint local: http://127.0.0.1:${PORT}/v1"
log "Config: ${THREADS} threads, ctx ${CTX}, timeout ${TIMEOUT}s"

for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    log "Daily Agent pronto."
    if [ -x "$HERMES_HOME/core-v2/venv/bin/python" ] && [ -f "$HERMES_HOME/core-v2/semantic_provider.py" ]; then
      (
        cd "$HERMES_HOME/core-v2"
        "$HERMES_HOME/core-v2/venv/bin/python" - <<'PY' >/dev/null 2>&1 || true
from semantic_provider import classify
classify('o que tenho amanhã', '')
PY
      )
      rm -f "$HERMES_HOME/core-v2/state/daily_agent_health.json"
      log "Warmup do classificador compacto concluído."
    fi
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
