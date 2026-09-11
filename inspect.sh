#!/usr/bin/env bash
set -u
TARGET_USER="${HERMES_TARGET_USER:-${SUDO_USER:-$(id -un)}}"
if command -v getent >/dev/null 2>&1; then
  TARGET_HOME="$(getent passwd "$TARGET_USER" 2>/dev/null | cut -d: -f6 || true)"
else TARGET_HOME=""; fi
[[ -n "$TARGET_HOME" ]] || TARGET_HOME="$HOME"
HERMES_HOME="${HERMES_HOME:-$TARGET_HOME/.hermes}"
export HERMES_HOME

run_as_target() {
  if [[ "${EUID:-$(id -u)}" -eq 0 && "$TARGET_USER" != "root" ]]; then
    sudo -u "$TARGET_USER" -H env HERMES_HOME="$HERMES_HOME" "$@"
  else env HERMES_HOME="$HERMES_HOME" "$@"; fi
}

if command -v hermes >/dev/null 2>&1; then HERMES_BIN="$(command -v hermes)"
elif [[ "${EUID:-$(id -u)}" -eq 0 && "$TARGET_USER" != "root" ]]; then
  HERMES_BIN="$(sudo -u "$TARGET_USER" -H bash -lc 'command -v hermes' 2>/dev/null || true)"
else HERMES_BIN=""; fi

echo '=== Hermes Local-Only / inspeção sem mutação ==='
echo "user=$TARGET_USER"
echo "hermes_home=$HERMES_HOME"
echo "hermes_bin=${HERMES_BIN:-NOT_FOUND}"
if [[ -n "$HERMES_BIN" ]]; then
  run_as_target "$HERMES_BIN" --version 2>/dev/null || true
  for key in model.provider model.default model.base_url model.context_length cron.model_provider cron.model delegation.provider delegation.model; do
    val="$(run_as_target "$HERMES_BIN" config get "$key" 2>/dev/null || true)"
    printf '%-24s %s\n' "$key=" "$val"
  done
  echo '--- gateway ---'
  run_as_target "$HERMES_BIN" gateway status 2>/dev/null || true
fi

echo '--- modelos locais ---'
if command -v ollama >/dev/null 2>&1; then ollama list 2>/dev/null || true; else echo 'ollama CLI não encontrado'; fi
curl -fsS --max-time 5 http://127.0.0.1:11434/v1/models 2>/dev/null | python3 -c '
import json,sys
try:
 d=json.load(sys.stdin); print("openai_compatible_models=" + ",".join(str(x.get("id","")) for x in d.get("data",[])))
except Exception: print("openai_compatible_models=UNAVAILABLE")
' 2>/dev/null || echo 'openai_compatible_models=UNAVAILABLE'

echo '--- rotinas (somente id/nome/provider/model; prompts NÃO são exibidos) ---'
J="$HERMES_HOME/cron/jobs.json"
if [[ -f "$J" ]]; then
  JOBS_FILE="$J" python3 - <<'PY'
import json, os
p=os.environ['JOBS_FILE']
try: data=json.load(open(p,encoding='utf-8'))
except Exception as e:
 print(f'jobs_json_error={e}'); raise SystemExit
rows=[]
def walk(x):
 if isinstance(x,dict):
  if x.get('job_id'):
   rows.append((x.get('job_id'),x.get('name',''),x.get('model_provider',''),x.get('model','')))
  for v in x.values(): walk(v)
 elif isinstance(x,list):
  for v in x: walk(v)
walk(data)
print(f'jobs_count={len(rows)}')
for r in rows: print('job=' + ' | '.join(str(v or '') for v in r))
PY
else echo 'jobs_count=0 (jobs.json não encontrado)'; fi

echo '--- arquivos relevantes ---'
for f in "$HERMES_HOME/config.yaml" "$HERMES_HOME/.env" "$HERMES_HOME/auth.json" "$HERMES_HOME/cron/jobs.json"; do
  [[ -e "$f" ]] && stat -c '%U:%G %a %n' "$f" 2>/dev/null || true
done

echo '--- nomes de variáveis LLM presentes no .env (SEM valores) ---'
if [[ -f "$HERMES_HOME/.env" ]]; then
  grep -E '^(OPENROUTER_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|.*BASE_URL|.*MODEL|.*PROVIDER)=' "$HERMES_HOME/.env" 2>/dev/null | cut -d= -f1 | sort -u || true
fi

echo '=== fim ==='
