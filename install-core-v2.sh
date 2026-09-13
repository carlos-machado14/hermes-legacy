#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HOME/.hermes/core-v2"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SYSTEMD_USER="$HOME/.config/systemd/user"
SCRIPTS="$HOME/.hermes/scripts"

log() { printf '[core-v3.2] %s\n' "$*"; }

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

mkdir -p "$TARGET" "$TARGET/state" "$TARGET/logs" "$SYSTEMD_USER" "$SCRIPTS"
chmod 700 "$TARGET/state" "$TARGET/logs" 2>/dev/null || true

for file in \
  hermes_core.py tools.py planner.py health_monitor.py local_briefs.py \
  memory_store.py action_executor.py tool_registry.py recovery_engine.py event_bus.py \
  project_registry.py incident_store.py watcher_engine.py api_server.py \
  project_ops.py project_commands.py goal_manager.py task_manager.py personal_memory.py \
  skill_registry.py opportunity_engine.py workflow_engine.py research_engine.py agent_router.py \
  onboarding_parser.py context_builder.py decision_log.py proactive_engine.py; do
  cp "$ROOT/core_v2/$file" "$TARGET/$file"
done
cp "$ROOT/core_v2/requirements.txt" "$TARGET/requirements.txt"
cp "$ROOT/core_v2/config.example.yaml" "$TARGET/config.example.yaml"

if [ ! -f "$TARGET/config.yaml" ]; then cp "$TARGET/config.example.yaml" "$TARGET/config.yaml"; chmod 600 "$TARGET/config.yaml" 2>/dev/null || true; fi

ensure_venv_support
if [ -d "$TARGET/venv" ]; then
  if [ ! -x "$TARGET/venv/bin/python" ] || ! "$TARGET/venv/bin/python" -m pip --version >/dev/null 2>&1; then log "Removendo venv incompleto/quebrado..."; rm -rf "$TARGET/venv"; fi
fi
if [ ! -x "$TARGET/venv/bin/python" ]; then log "Criando ambiente virtual..."; "$PYTHON_BIN" -m venv "$TARGET/venv"; fi
if ! "$TARGET/venv/bin/python" -m pip --version >/dev/null 2>&1; then log "pip ainda ausente no venv; tentando ensurepip..."; "$TARGET/venv/bin/python" -m ensurepip --upgrade; fi

log "Instalando dependencias..."
"$TARGET/venv/bin/python" -m pip install --upgrade pip
"$TARGET/venv/bin/python" -m pip install -r "$TARGET/requirements.txt"
chmod +x "$TARGET/hermes_core.py" "$TARGET/health_monitor.py" "$TARGET/local_briefs.py" "$TARGET/recovery_engine.py" "$TARGET/watcher_engine.py" "$TARGET/api_server.py"

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
Description=Hermes Core v3.2 Local API
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

systemctl --user daemon-reload
systemctl --user enable --now hermes-core-health.service hermes-core-watchers.service hermes-core-api.service
systemctl --user restart hermes-core-health.service hermes-core-watchers.service hermes-core-api.service

log "Validando imports..."
(
  cd "$TARGET"
  "$TARGET/venv/bin/python" -c 'import httpx, psutil, yaml, feedparser, bs4; import tools, planner, local_briefs, memory_store, action_executor, tool_registry, recovery_engine, event_bus, project_registry, incident_store, watcher_engine, api_server, project_ops, project_commands, goal_manager, task_manager, personal_memory, skill_registry, opportunity_engine, workflow_engine, research_engine, onboarding_parser, context_builder, decision_log, proactive_engine, agent_router; print("dependencias Core v3.2 OK")'
)

log "Validando API..."; sleep 1; curl -fsS http://127.0.0.1:8090/health >/dev/null
log "Hermes Core v3.2 instalado/atualizado em $TARGET"
echo "Estado pessoal preservado em: $TARGET/state"
echo "Config pessoal preservada em: $TARGET/config.yaml"
echo "Context Builder + Decision Log + Proactive Engine: habilitados"
echo "API local: http://127.0.0.1:8090"
echo "Nenhuma cron, timezone, credencial, objetivo, tarefa ou dado pessoal foi criado/alterado pelo upgrade."