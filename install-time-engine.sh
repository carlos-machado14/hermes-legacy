#!/usr/bin/env bash
set -euo pipefail

TARGET="$HOME/.hermes/core-v2"
SYSTEMD_USER="$HOME/.config/systemd/user"
UNIT="$SYSTEMD_USER/hermes-time-engine.service"

if [ ! -x "$TARGET/venv/bin/python" ]; then
  echo "Core não instalado em $TARGET. Rode ./install-core-v2.sh primeiro."
  exit 1
fi
if [ ! -f "$TARGET/time_service.py" ]; then
  echo "time_service.py não encontrado em $TARGET. Rode ./install-core-v2.sh primeiro."
  exit 1
fi

mkdir -p "$SYSTEMD_USER"
cat > "$UNIT" <<EOF
[Unit]
Description=Hermes Time Engine - lembretes, rotinas e alertas
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$TARGET/venv/bin/python $TARGET/time_service.py
Restart=always
RestartSec=3
WorkingDirectory=$TARGET
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now hermes-time-engine.service
systemctl --user restart hermes-time-engine.service
sleep 1

if ! systemctl --user is-active --quiet hermes-time-engine.service; then
  echo "Falha ao iniciar hermes-time-engine.service"
  systemctl --user --no-pager --full status hermes-time-engine.service || true
  exit 1
fi

echo "Hermes Time Engine ativo."
systemctl --user --no-pager --full status hermes-time-engine.service | sed -n '1,12p'
