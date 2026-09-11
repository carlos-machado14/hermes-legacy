#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Run verify.sh as the Hermes user, not root." >&2
  exit 1
fi

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export HERMES_HOME
HERMES_BIN="${HERMES_BIN:-$(command -v hermes || true)}"
[[ -n "$HERMES_BIN" ]] || { echo 'ERRO: Hermes não encontrado'; exit 1; }

provider="$($HERMES_BIN config get model.provider 2>/dev/null || true)"
model="$($HERMES_BIN config get model.default 2>/dev/null || true)"
base="$($HERMES_BIN config get model.base_url 2>/dev/null || true)"
context="$($HERMES_BIN config get model.context_length 2>/dev/null || true)"
cron_provider="$($HERMES_BIN config get cron.model_provider 2>/dev/null || true)"
cron_model="$($HERMES_BIN config get cron.model 2>/dev/null || true)"

printf 'provider      : %s\nmodel         : %s\nbase_url      : %s\ncontext       : %s\ncron provider : %s\ncron model    : %s\n' \
  "$provider" "$model" "$base" "$context" "$cron_provider" "$cron_model"

[[ "$provider" == "custom" ]] || { echo 'ERRO: provider principal não é custom' >&2; exit 2; }
[[ -n "$model" ]] || { echo 'ERRO: modelo vazio' >&2; exit 3; }
[[ "$base" == http://127.0.0.1:*'/v1' ]] || { echo "ERRO: base_url não é loopback local: $base" >&2; exit 4; }

systemctl --user is-active --quiet hermes-local-llm.service || {
  systemctl --user --no-pager status hermes-local-llm.service || true
  echo 'ERRO: hermes-local-llm.service não está ativo' >&2
  exit 5
}
echo 'runtime service : OK'

curl -fsS --max-time 5 "${base%/}/models" >/dev/null
echo 'local /models  : OK'

if grep -q 'HERMES_MIN_CONTEXT_LENGTH' "$HERMES_HOME/hermes-agent/agent/model_metadata.py" 2>/dev/null; then
  echo 'context patch  : OK'
else
  echo 'ERRO: patch local de contexto não encontrado' >&2
  exit 6
fi

vault="$(grep '^OBSIDIAN_VAULT_PATH=' "$HERMES_HOME/.env" 2>/dev/null | tail -1 | cut -d= -f2- || true)"
[[ -n "$vault" && -d "$vault" ]] || { echo 'ERRO: vault Obsidian não encontrado' >&2; exit 7; }
[[ -f "$HERMES_HOME/skills/hermes-local-memory/SKILL.md" ]] || { echo 'ERRO: skill hermes-local-memory não encontrada' >&2; exit 8; }
echo "vault            : OK ($vault)"

J="$HERMES_HOME/cron/jobs.json"
if [[ -f "$J" ]]; then
  JOBS_FILE="$J" EXPECTED_MODEL="$model" python3 - <<'PY'
import json,os,sys
x=json.load(open(os.environ['JOBS_FILE'],encoding='utf-8'))
bad=[]; jobs=[]; seen=set()
def walk(v):
    if isinstance(v,dict):
        jid=v.get('id') or v.get('job_id')
        looks=bool(v.get('schedule') or v.get('prompt') or v.get('name'))
        if jid and looks and jid not in seen:
            seen.add(jid); jobs.append(v)
        for z in v.values(): walk(z)
    elif isinstance(v,list):
        for z in v: walk(z)
walk(x)
for v in jobs:
    p=v.get('model_provider')
    m=v.get('model')
    # An unpinned job is valid because cron.model_provider/model are local-only fleet defaults.
    if p and p != 'custom':
        bad.append((v.get('id') or v.get('job_id'),p,m))
    if m and m != os.environ['EXPECTED_MODEL']:
        bad.append((v.get('id') or v.get('job_id'),p,m))
print(f'rotinas verificadas: {len(jobs)}')
if bad:
    print('ERRO: rotinas ainda pinadas fora do local-only:')
    for r in bad: print(r)
    sys.exit(9)
PY
fi

systemctl --user is-active --quiet hermes-gateway.service && echo 'gateway service : OK' || echo 'gateway service : WARNING/not active'

echo 'Executando resposta real pelo Hermes (pode ser lenta na CPU)...'
timeout 900 "$HERMES_BIN" -z 'Responda somente: OK'
echo 'VERIFY OK'
