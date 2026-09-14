#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HOME/.hermes/core-v2"
SYSTEMD_USER="$HOME/.config/systemd/user"

log(){ printf '[core-v4] %s\n' "$*"; }

mkdir -p "$TARGET" "$TARGET/state" "$SYSTEMD_USER"
for file in job_store.py execution_planner.py result_validator.py execution_runtime.py mission_router.py durable_worker.py core_entry.py; do
  cp "$ROOT/core_v2/$file" "$TARGET/$file"
done
chmod +x "$TARGET/durable_worker.py" "$TARGET/core_entry.py"

cat > "$SYSTEMD_USER/hermes-core-durable-worker.service" <<EOF
[Unit]
Description=Hermes Core v4 Durable Mission Worker
After=network-online.target hermes-local-llm.service hermes-core-api.service
[Service]
Type=simple
ExecStart=$TARGET/venv/bin/python $TARGET/durable_worker.py
Restart=always
RestartSec=5
WorkingDirectory=$TARGET
Environment=PYTHONUNBUFFERED=1
[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now hermes-core-durable-worker.service
systemctl --user restart hermes-core-durable-worker.service

(
  cd "$TARGET"
  "$TARGET/venv/bin/python" - <<'PY'
from job_store import recover_interrupted, list_jobs
import execution_planner, result_validator, execution_runtime, mission_router
print('imports v4 OK; recovered=', recover_interrupted(), 'jobs=', len(list_jobs(None, 5)))
PY
)

log "Durable Mission Runtime ativo"
log "DB: $TARGET/state/jobs.sqlite3"
log "Comandos: missao: <objetivo> | meus jobs | status job <id> | retomar jobs"
