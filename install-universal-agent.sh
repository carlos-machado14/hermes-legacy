#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HOME/.hermes/core-v2"

log(){ printf '[assistant-v4.3] %s\n' "$*"; }

mkdir -p "$TARGET"
for file in capability_registry.py agent_catalog.py domain_router.py universal_planner.py universal_router.py \
  assistant_os.py assistant_router.py agent_orchestrator.py resource_manager.py audit_log.py \
  mission_router.py execution_runtime.py execution_planner.py core_entry.py; do
  cp "$ROOT/core_v2/$file" "$TARGET/$file"
done
chmod +x "$TARGET/core_entry.py"

(
  cd "$TARGET"
  "$TARGET/venv/bin/python" - <<'PY'
from capability_registry import list_capabilities, domains
from agent_catalog import list_agents
from domain_router import classify
from universal_planner import build
from universal_router import handle
from assistant_os import brief, attention
from resource_manager import snapshot
from agent_orchestrator import select_agents
print('domains=', domains())
print('agents=', sorted(list_agents()))
print('capabilities=', len(list_capabilities()))
print('route=', classify('corrija o build do meu projeto e depois veja minhas tarefas de hoje'))
print('selected_agents=', [x.get('name') for x in select_agents('pesquise uma solução e corrija meu projeto')])
print('resources=', snapshot())
print('assistant_ok=', bool(brief()) and bool(attention()))
print('status_ok=', bool(handle('status universal')))
PY
)

systemctl --user restart hermes-core-durable-worker.service 2>/dev/null || true
systemctl --user restart hermes-core-api.service 2>/dev/null || true
systemctl --user restart hermes-openai-bridge.service 2>/dev/null || true
systemctl --user restart hermes-gateway.service 2>/dev/null || true

log "General Assistant OS + Universal Agent Runtime ativos."
log "Comandos: meu dia | o que precisa da minha atenção | recursos | status universal | agentes | capacidades"
log "Missões: meus jobs | pausar job <id> | retomar job <id> | cancelar job <id>"
