#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HOME/.hermes/core-v2"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SYSTEMD_USER="$HOME/.config/systemd/user"
SCRIPTS="$HOME/.hermes/scripts"
MEMORY_VAULT="$HOME/.hermes/memory"
WORKSPACES="$HOME/.hermes/workspaces"

log() { printf '[core-v4.8] %s\n' "$*"; }

ensure_venv_support() {
  local pyver pkg probe
  pyver="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  pkg="python${pyver}-venv"; probe="$(mktemp -d)"
  if "$PYTHON_BIN" -m venv "$probe/test" >/dev/null 2>&1 && "$probe/test/bin/python" -m pip --version >/dev/null 2>&1; then rm -rf "$probe"; return 0; fi
  rm -rf "$probe"; log "Suporte completo a venv/pip ausente. Instalando $pkg e python3-pip..."
  if ! command -v apt-get >/dev/null 2>&1; then log "apt-get nao encontrado. Instale manualmente $pkg python3-pip e rode novamente."; exit 1; fi
  if [ "$(id -u)" -eq 0 ]; then apt-get update && apt-get install -y "$pkg" python3-pip
  elif command -v sudo >/dev/null 2>&1; then sudo apt-get update && sudo apt-get install -y "$pkg" python3-pip
  else log "Sem sudo. Rode: apt-get install -y $pkg python3-pip"; exit 1; fi
}

mkdir -p "$TARGET" "$TARGET/state" "$TARGET/logs" "$SYSTEMD_USER" "$SCRIPTS" "$WORKSPACES"
mkdir -p "$MEMORY_VAULT"/{profile,goals,projects,business,conversations,decisions,daily}
chmod 700 "$TARGET/state" "$TARGET/logs" "$MEMORY_VAULT" "$WORKSPACES" 2>/dev/null || true

# Copia todo o conjunto Python do Core antes de qualquer import/serviço. Isso evita
# upgrades parciais em que core_entry.py chega antes de mission_router,
# assistant_router, universal_router ou outros módulos adicionados em versões novas.
shopt -s nullglob
CORE_MODULES=("$ROOT"/core_v2/*.py)
if [ ${#CORE_MODULES[@]} -eq 0 ]; then
  log "Nenhum módulo Python encontrado em $ROOT/core_v2"
  exit 1
fi
for src in "${CORE_MODULES[@]}"; do
  cp "$src" "$TARGET/$(basename "$src")"
done
shopt -u nullglob

cp "$ROOT/core_v2/requirements.txt" "$TARGET/requirements.txt"
cp "$ROOT/core_v2/config.example.yaml" "$TARGET/config.example.yaml"

if [ ! -f "$TARGET/config.yaml" ]; then
  cp "$TARGET/config.example.yaml" "$TARGET/config.yaml"
  chmod 600 "$TARGET/config.yaml" 2>/dev/null || true
else
  if grep -Eq '^[[:space:]]*max_tokens:[[:space:]]*320[[:space:]]*$' "$TARGET/config.yaml"; then
    sed -i -E 's/^([[:space:]]*max_tokens:[[:space:]]*)320[[:space:]]*$/\1900/' "$TARGET/config.yaml"
    log "Limite legado de resposta atualizado: 320 -> 900 tokens"
  fi
fi

ensure_venv_support
if [ -d "$TARGET/venv" ]; then
  if [ ! -x "$TARGET/venv/bin/python" ] || ! "$TARGET/venv/bin/python" -m pip --version >/dev/null 2>&1; then log "Removendo venv incompleto/quebrado..."; rm -rf "$TARGET/venv"; fi
fi
if [ ! -x "$TARGET/venv/bin/python" ]; then log "Criando ambiente virtual..."; "$PYTHON_BIN" -m venv "$TARGET/venv"; fi
if ! "$TARGET/venv/bin/python" -m pip --version >/dev/null 2>&1; then log "pip ainda ausente no venv; tentando ensurepip..."; "$TARGET/venv/bin/python" -m ensurepip --upgrade; fi

log "Instalando dependencias..."
"$TARGET/venv/bin/python" -m pip install --upgrade pip
"$TARGET/venv/bin/python" -m pip install -r "$TARGET/requirements.txt"
chmod +x "$TARGET/hermes_core.py" "$TARGET/core_entry.py" "$TARGET/openai_bridge.py" "$TARGET/health_monitor.py" "$TARGET/local_briefs.py" "$TARGET/recovery_engine.py" "$TARGET/watcher_engine.py" "$TARGET/api_server.py" "$TARGET/autonomous_service.py" 2>/dev/null || true

log "Validando sintaxe do Core..."
"$TARGET/venv/bin/python" -m py_compile "$TARGET"/*.py

log "Inicializando Memory Vault leve..."
(
  cd "$TARGET"
  "$TARGET/venv/bin/python" -c 'from memory_vault import sync_state_snapshots, refresh_index, summary; sync_state_snapshots(); refresh_index(); print(summary())'
)

log "Validando camada GitHub..."
if command -v gh >/dev/null 2>&1; then
  gh auth status >/dev/null 2>&1 && log "GitHub CLI autenticada (fallback/admin local)" || log "GitHub CLI instalada sem sessão; integração de usuários deve ocorrer pelo Freud"
else
  log "GitHub CLI ausente; isso não impede integrações GitHub de usuários via Freud"
fi

log "Instalando wrappers genericos opcionais (nenhuma cron sera criada)..."
make_wrapper() {
  local path="$1" mode="$2"
  if [ -e "$path" ] && ! grep -q 'HERMES_MANAGED_WRAPPER=1' "$path" 2>/dev/null; then log "Preservando script do usuario: $path"; return 0; fi
  cat > "$path" <<EOF
#!/usr/bin/env bash
# HERMES_MANAGED_WRAPPER=1
set -euo pipefail
exec "$TARGET/venv/bin/python" "$TARGET/local_briefs.py" "$mode"
EOF
  chmod +x "$path"
}
make_wrapper "$SCRIPTS/ai-daily-brief.sh" ai
make_wrapper "$SCRIPTS/marketing-leads-brief.sh" marketing
make_wrapper "$SCRIPTS/product-opportunity-brief.sh" product
make_wrapper "$SCRIPTS/financial-subscriptions-brief.sh" finance

cat > "$SYSTEMD_USER/hermes-core-health.service" <<EOF
[Unit]
Description=Hermes Core Health + Recovery
After=network-online.target hermes-local-llm.service hermes-gateway.service
[Service]
Type=simple
ExecStart=$TARGET/venv/bin/python $TARGET/health_monitor.py
Restart=always
RestartSec=5
WorkingDirectory=$TARGET
Environment=PYTHONUNBUFFERED=1
[Install]
WantedBy=default.target
EOF

cat > "$SYSTEMD_USER/hermes-core-watchers.service" <<EOF
[Unit]
Description=Hermes Core Watchers + Incident Detection
After=network-online.target hermes-core-health.service
[Service]
Type=simple
ExecStart=$TARGET/venv/bin/python $TARGET/watcher_engine.py
Restart=always
RestartSec=5
WorkingDirectory=$TARGET
Environment=PYTHONUNBUFFERED=1
[Install]
WantedBy=default.target
EOF

cat > "$SYSTEMD_USER/hermes-core-api.service" <<EOF
[Unit]
Description=Hermes Core Local API
After=network-online.target hermes-core-health.service
[Service]
Type=simple
ExecStart=$TARGET/venv/bin/python $TARGET/api_server.py
Restart=always
RestartSec=5
WorkingDirectory=$TARGET
Environment=PYTHONUNBUFFERED=1
Environment=HERMES_CORE_API_HOST=127.0.0.1
Environment=HERMES_CORE_API_PORT=8090
EnvironmentFile=-%h/.config/hermes/core-api.env
[Install]
WantedBy=default.target
EOF

cat > "$SYSTEMD_USER/hermes-openai-bridge.service" <<EOF
[Unit]
Description=Hermes Unified OpenAI Bridge for App/Voice
After=network-online.target hermes-core-api.service hermes-local-llm.service
[Service]
Type=simple
ExecStart=$TARGET/venv/bin/python $TARGET/openai_bridge.py
Restart=always
RestartSec=5
WorkingDirectory=$TARGET
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-%h/.config/hermes/core-api.env
[Install]
WantedBy=default.target
EOF

cat > "$SYSTEMD_USER/hermes-core-autonomous.service" <<EOF
[Unit]
Description=Hermes Core Autonomous General Agent
After=network-online.target hermes-gateway.service hermes-core-api.service
[Service]
Type=simple
ExecStart=$TARGET/venv/bin/python $TARGET/autonomous_service.py
Restart=always
RestartSec=10
WorkingDirectory=$TARGET
Environment=PYTHONUNBUFFERED=1
[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now hermes-core-health.service hermes-core-watchers.service hermes-core-api.service hermes-openai-bridge.service hermes-core-autonomous.service
systemctl --user restart hermes-core-health.service hermes-core-watchers.service hermes-core-api.service hermes-openai-bridge.service hermes-core-autonomous.service

log "Validando imports do Core completo..."
(
  cd "$TARGET"
  "$TARGET/venv/bin/python" - <<'PY'
import importlib
required = [
    'core_entry','mission_router','assistant_router','assistant_os',
    'universal_router','universal_planner','domain_router','capability_registry',
    'complexity_router','telemetry',
    'agent_catalog','agent_orchestrator','job_store','execution_planner',
    'execution_runtime','result_validator','resource_manager','audit_log',
    'api_server','openai_bridge','memory_vault','developer_router'
]
for name in required:
    importlib.import_module(name)
print('dependencias Hermes Core v4.8 OK')
PY
)

log "Validando APIs..."; sleep 1
curl -fsS http://127.0.0.1:8090/health >/dev/null
curl -fsS http://127.0.0.1:${HERMES_OPENAI_BRIDGE_PORT:-8091}/health >/dev/null || true
log "Hermes Core v4.8 instalado/atualizado em $TARGET"
echo "Memory Vault: $MEMORY_VAULT"
echo "Workspaces GitHub: $WORKSPACES"
echo "Indice leve SQLite: $TARGET/state/memory_index.sqlite3"
echo "Telemetria de performance: $TARGET/logs/perf.jsonl"
echo "Estado pessoal preservado em: $TARGET/state"
echo "Memoria longa seletiva + conversa curta + JSON estruturado: ativos"
echo "SLA fast/normal/hard/mission + roteamento por complexidade: ativos"
echo "GitHub CLI local: apenas fallback/admin; usuários conectam pelo Freud"
echo "API local Core: http://127.0.0.1:8090"
echo "Bridge OpenAI/app/voz: porta ${HERMES_OPENAI_BRIDGE_PORT:-8091}"
echo "Nenhuma cron, timezone, credencial, objetivo, tarefa ou dado pessoal foi criado/alterado pelo upgrade."
