#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HOME/.hermes/core-v2"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SYSTEMD_USER="$HOME/.config/systemd/user"
SCRIPTS="$HOME/.hermes/scripts"
MEMORY_VAULT="$HOME/.hermes/memory"
WORKSPACES="$HOME/.hermes/workspaces"

log() { printf '[core-v3.7] %s\n' "$*"; }

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

for file in \
  hermes_core.py tools.py planner.py health_monitor.py local_briefs.py \
  memory_store.py action_executor.py tool_registry.py recovery_engine.py event_bus.py \
  project_registry.py incident_store.py watcher_engine.py api_server.py openai_bridge.py \
  project_ops.py project_commands.py goal_manager.py task_manager.py personal_memory.py \
  skill_registry.py opportunity_engine.py workflow_engine.py research_engine.py agent_router.py \
  onboarding_parser.py context_builder.py decision_log.py proactive_engine.py \
  proactive_settings.py autonomous_service.py action_queue.py autonomy_settings.py goal_execution_engine.py \
  lead_manager.py crm_engine.py deep_research.py opportunity_hunter.py learning_engine.py business_router.py \
  conversation_memory.py contextual_router.py core_entry.py memory_vault.py memory_router.py site_sales_workflow.py \
  github_workspace.py developer_router.py; do
  cp "$ROOT/core_v2/$file" "$TARGET/$file"
done
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
chmod +x "$TARGET/hermes_core.py" "$TARGET/core_entry.py" "$TARGET/openai_bridge.py" "$TARGET/health_monitor.py" "$TARGET/local_briefs.py" "$TARGET/recovery_engine.py" "$TARGET/watcher_engine.py" "$TARGET/api_server.py" "$TARGET/autonomous_service.py"

log "Inicializando Memory Vault leve..."
(
  cd "$TARGET"
  "$TARGET/venv/bin/python" -c 'from memory_vault import sync_state_snapshots, refresh_index, summary; sync_state_snapshots(); refresh_index(); print(summary())'
)

log "Validando camada GitHub..."
if command -v gh >/dev/null 2>&1; then
  gh auth status >/dev/null 2>&1 && log "GitHub CLI autenticada" || log "GitHub CLI instalada; execute 'gh auth login' uma vez para conectar a conta"
else
  log "GitHub CLI ausente; instale com: sudo apt-get update && sudo apt-get install -y gh"
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
Description=Hermes Core v3 Health + Recovery
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
Description=Hermes Core v3 Watchers + Incident Detection
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
Description=Hermes Core v3.7 Local API
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
Description=Hermes Core v3.7 Autonomous Personal + Business Agent
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

log "Validando imports..."
(
  cd "$TARGET"
  "$TARGET/venv/bin/python" -c 'import httpx, psutil, yaml, feedparser, bs4, sqlite3; import tools, planner, local_briefs, memory_store, action_executor, tool_registry, recovery_engine, event_bus, project_registry, incident_store, watcher_engine, api_server, openai_bridge, project_ops, project_commands, goal_manager, task_manager, personal_memory, skill_registry, opportunity_engine, workflow_engine, research_engine, onboarding_parser, context_builder, decision_log, proactive_engine, proactive_settings, autonomous_service, action_queue, autonomy_settings, goal_execution_engine, lead_manager, crm_engine, deep_research, opportunity_hunter, learning_engine, business_router, conversation_memory, contextual_router, memory_vault, memory_router, site_sales_workflow, github_workspace, developer_router, core_entry, agent_router; print("dependencias Core v3.7 OK")'
)

log "Validando APIs..."; sleep 1
curl -fsS http://127.0.0.1:8090/health >/dev/null
curl -fsS http://127.0.0.1:${HERMES_OPENAI_BRIDGE_PORT:-8091}/health >/dev/null || true
log "Hermes Core v3.7 instalado/atualizado em $TARGET"
echo "Memory Vault: $MEMORY_VAULT"
echo "Workspaces GitHub: $WORKSPACES"
echo "Indice leve SQLite: $TARGET/state/memory_index.sqlite3"
echo "Estado pessoal e de negocios preservado em: $TARGET/state"
echo "Memoria longa seletiva + conversa curta + JSON estruturado: ativos"
echo "Workflow diario de sites: ativo quando vinculado ao objetivo"
echo "GitHub Workspace: leitura/clonagem/branch/commit local + ações remotas com aprovação"
echo "API local Core: http://127.0.0.1:8090"
echo "Bridge OpenAI/app/voz: porta ${HERMES_OPENAI_BRIDGE_PORT:-8091} (host configuravel em ~/.config/hermes/core-api.env)"
echo "Nenhuma cron, timezone, credencial, objetivo, tarefa ou dado pessoal foi criado/alterado pelo upgrade."
