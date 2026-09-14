#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HOME/.hermes/core-v2"
SEARX_DIR="$HOME/.hermes/searxng"

log(){ printf '[web-v4.1] %s\n' "$*"; }

mkdir -p "$TARGET" "$SEARX_DIR"
for file in web_search_engine.py browser_tools.py site_crawler.py site_auditor.py web_research.py web_router.py execution_planner.py execution_runtime.py core_entry.py; do
  cp "$ROOT/core_v2/$file" "$TARGET/$file"
done
cp "$ROOT/core_v2/requirements.txt" "$TARGET/requirements.txt"

log "Instalando dependências Python da pesquisa web..."
"$TARGET/venv/bin/python" -m pip install -r "$TARGET/requirements.txt"

if ! "$TARGET/venv/bin/python" -m playwright install chromium >/dev/null 2>&1; then
  log "Chromium do Playwright não pôde ser instalado automaticamente; crawler HTTP continuará funcionando."
else
  log "Playwright Chromium instalado."
fi

if command -v docker >/dev/null 2>&1; then
  SECRET_FILE="$SEARX_DIR/.secret"
  if [ ! -s "$SECRET_FILE" ]; then
    umask 077
    python3 - <<'PY' > "$SECRET_FILE"
import secrets
print(secrets.token_hex(32))
PY
  fi
  SECRET="$(cat "$SECRET_FILE")"
  cat > "$SEARX_DIR/settings.yml" <<EOF
use_default_settings: true
server:
  secret_key: "$SECRET"
  bind_address: "0.0.0.0"
  port: 8080
  limiter: false
search:
  safe_search: 1
  formats:
    - html
    - json
ui:
  static_use_hash: true
EOF
  cat > "$SEARX_DIR/docker-compose.yml" <<'EOF'
services:
  searxng:
    image: searxng/searxng:latest
    container_name: hermes-searxng
    restart: unless-stopped
    ports:
      - "127.0.0.1:8087:8080"
    volumes:
      - ./settings.yml:/etc/searxng/settings.yml:ro
    environment:
      - SEARXNG_BASE_URL=http://127.0.0.1:8087/
EOF
  log "Subindo SearXNG local em 127.0.0.1:8087..."
  (cd "$SEARX_DIR" && docker compose up -d)
else
  log "Docker ausente; SearXNG não foi iniciado. Pesquisa local exigirá HERMES_SEARXNG_URL externo."
fi

sleep 2
printf 'SearXNG: '
curl -fsS 'http://127.0.0.1:8087/search?q=hermes&format=json' >/dev/null 2>&1 && echo active || echo unavailable
printf 'Playwright: '
"$TARGET/venv/bin/python" - <<'PY'
from browser_tools import available
print('active' if available() else 'unavailable')
PY
printf 'Crawler/Auditor: '
"$TARGET/venv/bin/python" - <<'PY'
import site_crawler, site_auditor, web_research, web_router
print('active')
PY

systemctl --user restart hermes-core-durable-worker.service 2>/dev/null || true
systemctl --user restart hermes-gateway.service 2>/dev/null || true
log "Pesquisa real + navegador + crawler + auditor instalados."
