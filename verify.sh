#!/usr/bin/env bash
set -Eeuo pipefail
TARGET_USER="${HERMES_TARGET_USER:-${SUDO_USER:-$(id -un)}}"
TARGET_HOME="$(getent passwd "$TARGET_USER" 2>/dev/null | cut -d: -f6 || true)"
[[ -n "$TARGET_HOME" ]] || TARGET_HOME="$HOME"
HERMES_HOME="${HERMES_HOME:-$TARGET_HOME/.hermes}"
export HERMES_HOME
run_as_target(){ if [[ "${EUID:-$(id -u)}" -eq 0 && "$TARGET_USER" != root ]]; then sudo -u "$TARGET_USER" -H env HERMES_HOME="$HERMES_HOME" "$@"; else env HERMES_HOME="$HERMES_HOME" "$@"; fi; }
if command -v hermes >/dev/null 2>&1; then HERMES_BIN="$(command -v hermes)"; else HERMES_BIN="$(sudo -u "$TARGET_USER" -H bash -lc 'command -v hermes' 2>/dev/null || true)"; fi
[[ -n "$HERMES_BIN" ]] || { echo 'ERRO: Hermes não encontrado'; exit 1; }
provider="$(run_as_target "$HERMES_BIN" config get model.provider 2>/dev/null || true)"
model="$(run_as_target "$HERMES_BIN" config get model.default 2>/dev/null || true)"
base="$(run_as_target "$HERMES_BIN" config get model.base_url 2>/dev/null || true)"
context="$(run_as_target "$HERMES_BIN" config get model.context_length 2>/dev/null || true)"
cron_provider="$(run_as_target "$HERMES_BIN" config get cron.model_provider 2>/dev/null || true)"
cron_model="$(run_as_target "$HERMES_BIN" config get cron.model 2>/dev/null || true)"
printf 'provider      : %s\nmodel         : %s\nbase_url      : %s\ncontext       : %s\ncron provider : %s\ncron model    : %s\n' "$provider" "$model" "$base" "$context" "$cron_provider" "$cron_model"
[[ "$provider" == *custom* ]] || { echo 'ERRO: provider principal não é custom' >&2; exit 2; }
[[ -n "$model" ]] || { echo 'ERRO: modelo vazio' >&2; exit 3; }
[[ -n "$base" ]] || { echo 'ERRO: base_url vazio' >&2; exit 4; }
curl -fsS --max-time 10 "${base%/}/models" >/dev/null
echo 'API local: OK'

J="$HERMES_HOME/cron/jobs.json"
if [[ -f "$J" ]]; then
  JOBS_FILE="$J" EXPECTED_MODEL="$model" python3 - <<'PY'
import json,os,sys
x=json.load(open(os.environ['JOBS_FILE'],encoding='utf-8')); bad=[]; total=0
def walk(v):
 global total
 if isinstance(v,dict):
  if v.get('job_id'):
   total+=1
   if v.get('model_provider')!='custom' or v.get('model')!=os.environ['EXPECTED_MODEL']:
    bad.append((v.get('job_id'),v.get('model_provider'),v.get('model')))
  for z in v.values(): walk(z)
 elif isinstance(v,list):
  for z in v: walk(z)
walk(x)
print(f'rotinas verificadas: {total}')
if bad:
 print('ERRO: rotinas ainda pinadas fora do local-only:')
 for r in bad: print(r)
 sys.exit(5)
PY
fi

echo 'Executando uma resposta real pelo Hermes...'
run_as_target "$HERMES_BIN" -z 'Responda somente: OK'
echo 'VERIFY OK'
