#!/usr/bin/env bash
set -u

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Run inspect.sh as the Hermes user, not root." >&2
  exit 1
fi

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export HERMES_HOME
HERMES_BIN="${HERMES_BIN:-$(command -v hermes || true)}"

echo '=== Hermes Local Stack / inspeção sem mutação ==='
echo "user=$(id -un)"
echo "hermes_home=$HERMES_HOME"
echo "hermes_bin=${HERMES_BIN:-NOT_FOUND}"

if [[ -n "$HERMES_BIN" ]]; then
  "$HERMES_BIN" --version 2>/dev/null || true
  for key in model.provider model.default model.base_url model.context_length cron.model_provider cron.model delegation.provider delegation.model compression.threshold_tokens compression.proactive_prune_tokens; do
    val="$($HERMES_BIN config get "$key" 2>/dev/null || true)"
    printf '%-40s %s\n' "$key=" "$val"
  done
fi

echo '--- source checkout ---'
SRC="$HERMES_HOME/hermes-agent"
if [[ -d "$SRC/.git" ]]; then
  printf 'branch='; git -C "$SRC" branch --show-current 2>/dev/null || true
  printf 'head='; git -C "$SRC" rev-parse --short HEAD 2>/dev/null || true
  echo "working_tree_changes=$(git -C "$SRC" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  if grep -q 'HERMES_MIN_CONTEXT_LENGTH' "$SRC/agent/model_metadata.py" 2>/dev/null; then
    echo 'local_context_patch=YES'
  else
    echo 'local_context_patch=NO'
  fi
fi

echo '--- services ---'
for service in hermes-local-llm.service hermes-gateway.service; do
  if systemctl --user cat "$service" >/dev/null 2>&1; then
    echo "$service=$(systemctl --user is-active "$service" 2>/dev/null || true)"
  else
    echo "$service=NOT_INSTALLED"
  fi
done

echo '--- local endpoint ---'
if curl -fsS --max-time 3 http://127.0.0.1:8088/v1/models >/tmp/hermes-local-models.json 2>/dev/null; then
  python3 - <<'PY'
import json
p=json.load(open('/tmp/hermes-local-models.json'))
print('models=' + ','.join(str(x.get('id','')) for x in p.get('data',[]) if isinstance(x,dict)))
PY
else
  echo 'models=UNAVAILABLE_ON_127.0.0.1:8088'
fi

echo '--- cron jobs (sem prompts) ---'
J="$HERMES_HOME/cron/jobs.json"
if [[ -f "$J" ]]; then
  JOBS_FILE="$J" python3 - <<'PY'
import json,os
try: data=json.load(open(os.environ['JOBS_FILE'],encoding='utf-8'))
except Exception as e:
 print(f'jobs_json_error={e}'); raise SystemExit
seen=set(); rows=[]
def walk(x):
 if isinstance(x,dict):
  jid=x.get('id') or x.get('job_id')
  looks=bool(x.get('schedule') or x.get('prompt') or x.get('name'))
  if jid and looks and jid not in seen:
   seen.add(jid); rows.append((jid,x.get('name',''),x.get('model_provider',''),x.get('model','')))
  for v in x.values(): walk(v)
 elif isinstance(x,list):
  for v in x: walk(v)
walk(data)
print(f'jobs_count={len(rows)}')
for r in rows: print('job=' + ' | '.join(str(v or '') for v in r))
PY
else
  echo 'jobs_count=0 (jobs.json não encontrado)'
fi

echo '--- knowledge / memory ---'
vault="$(grep '^OBSIDIAN_VAULT_PATH=' "$HERMES_HOME/.env" 2>/dev/null | tail -1 | cut -d= -f2- || true)"
echo "obsidian_vault=${vault:-NOT_CONFIGURED}"
echo "builtin_memories=$HERMES_HOME/memories"
[[ -d "$HERMES_HOME/memories" ]] && find "$HERMES_HOME/memories" -maxdepth 1 -type f -printf '%f\n' 2>/dev/null | sort || true

echo '--- relevant files ---'
for f in "$HERMES_HOME/config.yaml" "$HERMES_HOME/.env" "$HERMES_HOME/auth.json" "$HERMES_HOME/cron/jobs.json"; do
  [[ -e "$f" ]] && stat -c '%U:%G %a %n' "$f" 2>/dev/null || true
done

echo '=== fim ==='
