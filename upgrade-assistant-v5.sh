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

log "1/8 Validando sintaxe do pacote antes do upgrade..."
"$PYTHON_BIN" -m py_compile "$ROOT"/core_v2/*.py "$ROOT"/plugins/hermes-core-fastpath/__init__.py
bash -n "$ROOT/install-core-v2.sh"
bash -n "$ROOT/install-gateway-fastpath-plugin.sh"

log "2/8 Instalando/atualizando Hermes Core e dependências..."
bash "$ROOT/install-core-v2.sh"

log "3/8 Rodando contratos completos no venv instalado..."
(
  cd "$ROOT"
  PYTHONPATH="$ROOT/core_v2" "$TARGET/venv/bin/python" -m unittest discover -s tests -p 'test_*.py'
)

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

log "4/8 Ativando serviços de multi-flow e agenda interna..."
systemctl --user daemon-reload
systemctl --user enable --now hermes-core-durable.service hermes-core-time.service
systemctl --user restart hermes-core-durable.service hermes-core-time.service hermes-core-autonomous.service

log "5/8 Ativando proatividade e autonomia segura solicitadas..."
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

log "6/8 Instalando FastPath multi-flow no gateway..."
bash "$ROOT/install-gateway-fastpath-plugin.sh"

log "7/8 Smoke tests de agenda, multi-flow e classificação..."
(
  cd "$TARGET"
  "$TARGET/venv/bin/python" - <<'PY'
import tempfile
from pathlib import Path

import job_store
from complexity_router import classify
from temporal_parser import parse

assert classify('Qual a capital da Itália?').tier == 'normal'
assert classify('Quero encontrar um possível cliente em Colombo PR que esteja perdendo oportunidade por não ter uma boa presença digital. Analise e me traga o melhor.').tier == 'mission'

water = parse('me lembre de beber água a cada 15 minutos das 8h até 17h de segunda a sexta')
assert water and water['recurrence']['minutes'] == 15
assert water['recurrence']['window_start'] == '08:00'
assert water['recurrence']['window_end'] == '17:00'
assert water['recurrence']['weekdays'] == [0,1,2,3,4]

monthly = parse('me lembre todo dia 28 do nosso aniversário de namoro')
assert monthly and monthly['recurrence']['freq'] == 'monthly' and monthly['recurrence']['day'] == 28

daily = parse('todo dia às 8 me lembre de revisar minhas prioridades')
assert daily and daily['recurrence']['time'] == '08:00'

old_db = job_store.DB_PATH
with tempfile.TemporaryDirectory() as tmp:
    job_store.DB_PATH = Path(tmp) / 'jobs.sqlite3'
    a = job_store.create_job('pesquisa A', source_platform='telegram', source_chat_id='smoke')
    b = job_store.create_job('pesquisa B', source_platform='telegram', source_chat_id='smoke')
    claimed = job_store.claim_jobs(2)
    assert {x['id'] for x in claimed} == {a['id'], b['id']}
job_store.DB_PATH = old_db

print('smoke tests assistant v5 OK')
PY
)

log "8/8 Verificando serviços..."
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
- lembretes/rotinas com janela, dias, horários e recorrência: ativos
- retry e deduplicação de entregas: ativos
- pesquisa comercial filtra artigos/diretórios e qualifica candidatos reais
- coleta de contatos, redes, imagens e logos públicos: ativa
- proatividade orientada a objetivos: ativa
- FastPath sem fila global única: ativo

Testes rápidos sugeridos no Telegram:
1) me lembre de beber água a cada 15 minutos das 8h até 17h de segunda a sexta
2) me lembre todo dia 28 do nosso aniversário de namoro
3) todo dia às 8 me lembre de revisar minhas prioridades
4) o que tenho hoje?
5) Quero encontrar um possível cliente em Colombo PR que esteja perdendo oportunidade por não ter uma boa presença digital. Analise e me traga o melhor.
   Depois envie outra pergunta imediatamente; ela deve responder sem interromper o fluxo anterior.
EOF
