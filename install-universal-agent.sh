#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HOME/.hermes/core-v2"

log(){ printf '[universal-v4.2] %s\n' "$*"; }

mkdir -p "$TARGET"
for file in capability_registry.py agent_catalog.py domain_router.py universal_planner.py universal_router.py execution_planner.py core_entry.py; do
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
print('domains=', domains())
print('agents=', sorted(list_agents()))
print('capabilities=', len(list_capabilities()))
print('route=', classify('corrija o build do meu projeto e depois veja minhas tarefas de hoje'))
print('status_ok=', bool(handle('status universal')))
PY
)

systemctl --user restart hermes-core-durable-worker.service 2>/dev/null || true
systemctl --user restart hermes-core-api.service 2>/dev/null || true
systemctl --user restart hermes-openai-bridge.service 2>/dev/null || true
systemctl --user restart hermes-gateway.service 2>/dev/null || true

log "Universal Agent Runtime ativo."
log "Comandos: status universal | agentes | capacidades | roteie <pedido> | plano universal <pedido>"
