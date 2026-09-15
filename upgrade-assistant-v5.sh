#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HOME/.hermes/core-v2"
SYSTEMD_USER="$HOME/.config/systemd/user"
PYTHON_BIN="${PYTHON_BIN:-python3}"

log() { printf '[assistant-v5] %s\n' "$*"; }

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Execute como o usuário do Hermes, não como root." >&2
  exit 1
fi

log "1/7 Validando contratos antes do upgrade..."
cd "$ROOT"
PYTHONPATH="$ROOT/core_v2" "$PYTHON_BIN" -m unittest discover -s tests -p 'test_*.py'

log "2/7 Instalando/atualizando Hermes Core..."
bash "$ROOT/install-core-v2.sh"

mkdir -p "$SYSTEMD_USER"
cat > "$SYSTEMD_USER/hermes-core-durable.service" <<EOF
[Unit]
Description=Hermes Multi-Flow Durable Worker
After=network-online.target hermes-core-api.service hermes-local-llm.service
[Service]
Type=simple
ExecStart=$TARGET/venv/bin/python $TARGET/durable_worker.py
Restart=always
RestartSec=5
WorkingDirectory=$TARGET
Environment=PYTHONUNBUFFERED=1
Environment=HERMES_FLOW_WORKERS=4
[Install]
WantedBy=default.target
EOF

cat > "$SYSTEMD_USER/hermes-core-time.service" <<EOF
[Unit]
Description=Hermes Local Time Engine - Agenda, Rotinas e Lembretes
After=network-online.target hermes-gateway.service
[Service]
Type=simple
ExecStart=$TARGET/venv/bin/python $TARGET/time_service.py
Restart=always
RestartSec=5
WorkingDirectory=$TARGET
Environment=PYTHONUNBUFFERED=1
Environment=HERMES_TIMEZONE=${HERMES_TIMEZONE:-America/Sao_Paulo}
[Install]
WantedBy=default.target
EOF

log "3/7 Ativando serviços de multi-flow e agenda interna..."
systemctl --user daemon-reload
systemctl --user enable --now hermes-core-durable.service hermes-core-time.service
systemctl --user restart hermes-core-durable.service hermes-core-time.service hermes-core-autonomous.service

log "4/7 Ativando proatividade e autonomia segura solicitadas..."
(
  cd "$TARGET"
  "$TARGET/venv/bin/python" - <<'PY'
from autonomy_settings import enable as enable_autonomy
from proactive_settings import enable as enable_proactive
print(enable_autonomy())
print(enable_proactive())
PY
)
systemctl --user restart hermes-core-autonomous.service

log "5/7 Instalando FastPath multi-flow no gateway..."
bash "$ROOT/install-gateway-fastpath-plugin.sh"

log "6/7 Smoke tests do Time Engine e roteamento semântico..."
(
  cd "$TARGET"
  "$TARGET/venv/bin/python" - <<'PY'
from complexity_router import classify
from temporal_parser import parse

assert classify('Qual a capital da Itália?').tier == 'normal'
assert classify('Quero encontrar um possível cliente em Colombo PR que esteja perdendo oportunidade por não ter uma boa presença digital. Analise e me traga o melhor.').tier == 'mission'
water = parse('me lembre de beber água a cada 15 minutos das 8h até 17h de segunda a sexta')
assert water and water['recurrence']['minutes'] == 15
assert water['recurrence']['window_start'] == '08:00'
assert water['recurrence']['window_end'] == '17:00'
monthly = parse('me lembre todo dia 28 do nosso aniversário de namoro')
assert monthly and monthly['recurrence']['freq'] == 'monthly' and monthly['recurrence']['day'] == 28
print('smoke tests v5 OK')
PY
)

log "7/7 Verificando serviços..."
for service in hermes-core-durable.service hermes-core-time.service hermes-core-autonomous.service hermes-gateway.service; do
  if systemctl --user is-active --quiet "$service"; then
    echo "OK  $service"
  else
    echo "ERRO $service" >&2
    systemctl --user status "$service" --no-pager >&2 || true
    exit 1
  fi
done

cat <<'EOF'

Hermes Assistant v5 atualizado com sucesso.
- multi-flow concorrente: ativo
- tarefas longas duráveis em background: ativo
- retorno automático ao finalizar: ativo
- agenda SQLite local: ativa
- lembretes/rotinas com janela, dias e recorrência: ativos
- retry e deduplicação de entregas: ativos
- proatividade orientada a objetivos: ativa
- FastPath sem fila global única: ativo

Testes rápidos sugeridos no Telegram:
1) me lembre de beber água a cada 15 minutos das 8h até 17h de segunda a sexta
2) me lembre todo dia 28 do nosso aniversário de namoro
3) o que tenho hoje?
4) Quero encontrar um possível cliente em Colombo PR que esteja perdendo oportunidade por não ter uma boa presença digital. Analise e me traga o melhor.
   Depois envie outra pergunta imediatamente; ela deve responder sem interromper o fluxo anterior.
EOF
