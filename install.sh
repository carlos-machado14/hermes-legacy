#!/usr/bin/env bash
set -Eeuo pipefail

# Hermes Local-Only
# Migra uma instalação EXISTENTE do Hermes para um único modelo local OpenAI-compatible.
# Não reinstala o Hermes, não recria rotinas e não remove credenciais de ferramentas.

STAMP="$(date +%Y%m%d-%H%M%S)"
TARGET_USER="${HERMES_TARGET_USER:-${SUDO_USER:-$(id -un)}}"
if [[ -z "$TARGET_USER" || "$TARGET_USER" == "root" ]]; then
  TARGET_USER="$(id -un)"
fi

if command -v getent >/dev/null 2>&1; then
  TARGET_HOME="$(getent passwd "$TARGET_USER" 2>/dev/null | cut -d: -f6 || true)"
else
  TARGET_HOME=""
fi
[[ -n "$TARGET_HOME" ]] || TARGET_HOME="$HOME"

# Respeita HERMES_HOME já usado pela instalação atual. Se sudo -E não o preservou,
# usa o home do usuário original em vez de /root/.hermes.
HERMES_HOME="${HERMES_HOME:-$TARGET_HOME/.hermes}"
export HERMES_HOME

OLLAMA_URL="${HERMES_LOCAL_OLLAMA_URL:-http://127.0.0.1:11434}"
BASE_URL="${HERMES_LOCAL_BASE_URL:-${OLLAMA_URL%/}/v1}"
CONTEXT_LENGTH="${HERMES_LOCAL_CONTEXT:-65536}"
MODEL="${HERMES_LOCAL_MODEL:-}"
BACKUP_DIR="$HERMES_HOME/backups/local-only-$STAMP"

log()  { printf '\n\033[1;36m[hermes-local]\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33m[hermes-local]\033[0m %s\n' "$*" >&2; }
die()  { printf '\n\033[1;31m[hermes-local]\033[0m %s\n' "$*" >&2; exit 1; }

run_as_target() {
  if [[ "${EUID:-$(id -u)}" -eq 0 && "$TARGET_USER" != "root" ]]; then
    sudo -u "$TARGET_USER" -H env HERMES_HOME="$HERMES_HOME" "$@"
  else
    env HERMES_HOME="$HERMES_HOME" "$@"
  fi
}

# Resolve o binário do Hermes no PATH do usuário real, não no secure_path do sudo.
if [[ -n "${HERMES_BIN:-}" ]]; then
  HERMES_BIN="$HERMES_BIN"
elif command -v hermes >/dev/null 2>&1; then
  HERMES_BIN="$(command -v hermes)"
elif [[ "${EUID:-$(id -u)}" -eq 0 && "$TARGET_USER" != "root" ]]; then
  HERMES_BIN="$(sudo -u "$TARGET_USER" -H bash -lc 'command -v hermes' 2>/dev/null || true)"
else
  HERMES_BIN=""
fi

[[ -n "$HERMES_BIN" ]] || die "Hermes não encontrado. Rode ./inspect.sh e confirme o PATH/HERMES_HOME da instalação atual."
command -v curl >/dev/null 2>&1 || die "curl não encontrado."
command -v python3 >/dev/null 2>&1 || die "python3 não encontrado."

log "Usuário Hermes : $TARGET_USER"
log "HERMES_HOME     : $HERMES_HOME"
log "Hermes bin      : $HERMES_BIN"
log "Endpoint local  : $BASE_URL"
run_as_target "$HERMES_BIN" --version 2>/dev/null || true

# Descobre o modelo já servido pela VPS. Não baixa modelo novo automaticamente.
if [[ -z "$MODEL" ]]; then
  MODELS_JSON="$(curl -fsS --max-time 10 "${BASE_URL%/}/models" 2>/dev/null || true)"
  if [[ -n "$MODELS_JSON" ]]; then
    MODEL="$(printf '%s' "$MODELS_JSON" | python3 -c '
import json,sys
try:
    data=json.load(sys.stdin)
    rows=data.get("data") or []
    print((rows[0].get("id") if rows else "") or "")
except Exception:
    print("")
' 2>/dev/null || true)"
  fi
fi
if [[ -z "$MODEL" ]] && command -v ollama >/dev/null 2>&1; then
  MODEL="$(ollama list 2>/dev/null | awk 'NR==2 {print $1; exit}' || true)"
fi
[[ -n "$MODEL" ]] || die "Nenhum modelo local detectado. Use HERMES_LOCAL_MODEL='nome:tag' sudo -E ./install.sh"

log "Modelo local selecionado: $MODEL"
curl -fsS --max-time 10 "${BASE_URL%/}/models" >/dev/null \
  || die "O endpoint $BASE_URL não respondeu em /models. Não alterei o Hermes."

# Backup antes de qualquer mutação. Inclui jobs.json porque versões atuais persistem pins
# de provider/model por rotina nesse arquivo.
log "Criando backup da instalação atual..."
if [[ "${EUID:-$(id -u)}" -eq 0 && "$TARGET_USER" != "root" ]]; then
  install -d -o "$TARGET_USER" -g "$(id -gn "$TARGET_USER")" "$HERMES_HOME/backups" "$BACKUP_DIR"
else
  mkdir -p "$BACKUP_DIR"
fi
for rel in config.yaml .env auth.json cron/jobs.json; do
  src="$HERMES_HOME/$rel"
  if [[ -f "$src" ]]; then
    mkdir -p "$BACKUP_DIR/$(dirname "$rel")"
    cp -a "$src" "$BACKUP_DIR/$rel"
  fi
done
if [[ -f /etc/systemd/system/ollama.service.d/hermes-local-only.conf ]]; then
  mkdir -p "$BACKUP_DIR/systemd"
  cp -a /etc/systemd/system/ollama.service.d/hermes-local-only.conf "$BACKUP_DIR/systemd/ollama.service.d.conf"
fi
cat > "$BACKUP_DIR/metadata.txt" <<META
created_at=$STAMP
target_user=$TARGET_USER
hermes_home=$HERMES_HOME
model=$MODEL
base_url=$BASE_URL
context_length=$CONTEXT_LENGTH
META
if [[ "${EUID:-$(id -u)}" -eq 0 && "$TARGET_USER" != "root" ]]; then
  chown -R "$TARGET_USER:$(id -gn "$TARGET_USER")" "$BACKUP_DIR"
fi
log "Backup: $BACKUP_DIR"

# Configuração principal: provider explícito custom impede resolução automática por API keys
# antigas que ainda possam existir para ferramentas/outros serviços.
log "Configurando o Hermes para inferência local-only..."
run_as_target "$HERMES_BIN" config set model.provider custom
run_as_target "$HERMES_BIN" config set model.base_url "$BASE_URL"
run_as_target "$HERMES_BIN" config set model.default "$MODEL"
run_as_target "$HERMES_BIN" config set model.context_length "$CONTEXT_LENGTH"

# Sem fallback para OpenRouter/Nous/Anthropic/etc. Mantemos as credenciais em disco porque
# algumas podem ser usadas por tools independentes; apenas deixamos de roteá-las como LLM.
run_as_target "$HERMES_BIN" fallback clear >/dev/null 2>&1 || true
run_as_target "$HERMES_BIN" config unset fallback_model >/dev/null 2>&1 || true
run_as_target "$HERMES_BIN" config unset fallback_providers >/dev/null 2>&1 || true
run_as_target "$HERMES_BIN" config unset model.api_key >/dev/null 2>&1 || true

# Toda a frota de cron usa o mesmo modelo local. Isso cobre jobs sem pin individual.
run_as_target "$HERMES_BIN" config set cron.model_provider custom >/dev/null 2>&1 || true
run_as_target "$HERMES_BIN" config set cron.model "$MODEL" >/dev/null 2>&1 || true

# Subagentes/delegação também ficam locais.
run_as_target "$HERMES_BIN" config set delegation.provider custom >/dev/null 2>&1 || true
run_as_target "$HERMES_BIN" config set delegation.model "$MODEL" >/dev/null 2>&1 || true

# Auxiliary tasks existentes podem ter ficado pinadas em providers externos. "main" força
# reutilização do modelo principal local. Campos antigos de endpoint/chave são removidos.
for task in compression vision title_generation; do
  run_as_target "$HERMES_BIN" config set "auxiliary.$task.provider" main >/dev/null 2>&1 || true
  run_as_target "$HERMES_BIN" config unset "auxiliary.$task.model" >/dev/null 2>&1 || true
  run_as_target "$HERMES_BIN" config unset "auxiliary.$task.base_url" >/dev/null 2>&1 || true
  run_as_target "$HERMES_BIN" config unset "auxiliary.$task.api_key" >/dev/null 2>&1 || true
done

# Migra pins POR JOB existentes. Isso é necessário porque um job criado/editado com
# --provider "OmniRoute NGC" --model combo-free continua usando esse pin mesmo após trocar
# o default global. Fazemos a edição diretamente no store, preservando IDs, agenda, prompt,
# histórico e estado do job.
JOBS_FILE="$HERMES_HOME/cron/jobs.json"
if [[ -f "$JOBS_FILE" ]]; then
  log "Migrando pins das rotinas existentes para custom/$MODEL..."
  if [[ "${EUID:-$(id -u)}" -eq 0 && "$TARGET_USER" != "root" ]]; then
    sudo -u "$TARGET_USER" -H env JOBS_FILE="$JOBS_FILE" LOCAL_MODEL="$MODEL" python3 - <<'PY'
import json, os, pathlib, tempfile
p = pathlib.Path(os.environ['JOBS_FILE'])
model = os.environ['LOCAL_MODEL']
data = json.loads(p.read_text(encoding='utf-8'))
count = 0

def walk(node):
    global count
    if isinstance(node, dict):
        if node.get('job_id'):
            node['model'] = model
            node['model_provider'] = 'custom'
            count += 1
        for value in node.values():
            walk(value)
    elif isinstance(node, list):
        for value in node:
            walk(value)

walk(data)
text = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
fd, tmp = tempfile.mkstemp(prefix='.jobs.local-only.', dir=str(p.parent), text=True)
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)
finally:
    if os.path.exists(tmp): os.unlink(tmp)
print(count)
PY
  else
    JOBS_FILE="$JOBS_FILE" LOCAL_MODEL="$MODEL" python3 - <<'PY'
import json, os, pathlib, tempfile
p = pathlib.Path(os.environ['JOBS_FILE'])
model = os.environ['LOCAL_MODEL']
data = json.loads(p.read_text(encoding='utf-8'))
count = 0

def walk(node):
    global count
    if isinstance(node, dict):
        if node.get('job_id'):
            node['model'] = model
            node['model_provider'] = 'custom'
            count += 1
        for value in node.values(): walk(value)
    elif isinstance(node, list):
        for value in node: walk(value)
walk(data)
fd, tmp = tempfile.mkstemp(prefix='.jobs.local-only.', dir=str(p.parent), text=True)
try:
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)
finally:
    if os.path.exists(tmp): os.unlink(tmp)
print(count)
PY
  fi
else
  warn "Nenhum $JOBS_FILE encontrado; não há rotinas persistidas nesse HERMES_HOME ou elas usam outro profile."
fi

# Ajuste do Ollama para VPS pequena: uma geração e um modelo residentes por vez.
# Só root mexe em systemd; o restante da migração já foi feito como usuário Hermes.
if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^ollama.service'; then
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    log "Ajustando Ollama para fila única..."
    mkdir -p /etc/systemd/system/ollama.service.d
    cat > /etc/systemd/system/ollama.service.d/hermes-local-only.conf <<SYS
[Service]
Environment="OLLAMA_CONTEXT_LENGTH=$CONTEXT_LENGTH"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_KEEP_ALIVE=10m"
SYS
    systemctl daemon-reload
    systemctl restart ollama
    for _ in {1..30}; do
      curl -fsS --max-time 2 "${BASE_URL%/}/models" >/dev/null 2>&1 && break
      sleep 2
    done
  else
    warn "Sem root: não alterei o serviço Ollama. Rode novamente com sudo -E para aplicar a fila única."
  fi
fi

# Reinicia gateway como o mesmo usuário que possui ~/.hermes; nunca como root.
log "Reiniciando gateway Hermes..."
run_as_target "$HERMES_BIN" gateway restart >/dev/null 2>&1 || true

log "Configuração efetiva após migração:"
printf 'provider : '; run_as_target "$HERMES_BIN" config get model.provider 2>/dev/null || true
printf 'model    : '; run_as_target "$HERMES_BIN" config get model.default 2>/dev/null || true
printf 'base_url : '; run_as_target "$HERMES_BIN" config get model.base_url 2>/dev/null || true
printf 'context  : '; run_as_target "$HERMES_BIN" config get model.context_length 2>/dev/null || true
printf 'cron     : '; run_as_target "$HERMES_BIN" config get cron.model_provider 2>/dev/null || true; printf '/'; run_as_target "$HERMES_BIN" config get cron.model 2>/dev/null || true

log "Testando endpoint OpenAI-compatible local..."
PROBE="$(MODEL="$MODEL" python3 - <<'PY'
import json, os
print(json.dumps({'model': os.environ['MODEL'], 'messages':[{'role':'user','content':'Responda somente: OK'}], 'stream':False, 'max_tokens':8}))
PY
)"
if curl -fsS --max-time 240 -H 'Content-Type: application/json' -d "$PROBE" \
  "${BASE_URL%/}/chat/completions" >/tmp/hermes-local-only-probe.json 2>/dev/null; then
  log "Inferência direta local: OK"
else
  warn "O /models respondeu, mas /chat/completions falhou. O backup está intacto; rode ./verify.sh para diagnóstico."
fi

cat <<DONE

============================================================
HERMES LOCAL-ONLY APLICADO
============================================================
Usuário  : $TARGET_USER
Home     : $HERMES_HOME
Provider : custom
Modelo   : $MODEL
Endpoint : $BASE_URL
Contexto : $CONTEXT_LENGTH
Cron     : migrado para custom/$MODEL
Fallback : removido
Backup   : $BACKUP_DIR

Próximo comando:
  ./verify.sh
============================================================
DONE
