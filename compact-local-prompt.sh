#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Run compact-local-prompt.sh as the Hermes user, not root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export HERMES_HOME
HERMES_BIN="${HERMES_BIN:-$(command -v hermes || true)}"
[[ -n "$HERMES_BIN" ]] || { echo "Hermes CLI not found" >&2; exit 1; }
[[ -f "$HERMES_HOME/config.yaml" ]] || { echo "Missing $HERMES_HOME/config.yaml" >&2; exit 1; }

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$HERMES_HOME/backups/compact-local-prompt-$STAMP"
mkdir -p "$BACKUP"
cp -a "$HERMES_HOME/config.yaml" "$BACKUP/config.yaml"

echo "[compact-prompt] backup=$BACKUP"

# The local 4B CPU model pays heavily for every fixed token. Keep the
# progressive-disclosure bridge, but defer every ordinary capability,
# including structured clarify. The model can still ask a plain-text
# clarification without paying the 4 KB clarify schema on every turn.
DEFER='[clarify, web_search, web_extract, terminal, process, process_manage, read_file, write_file, patch, search_files, vision_analyze, image_generate, skills_list, skill_view, skill_manage, browser_exec, text_to_speech, todo, todo_list, memory, session_search, execute_code, delegate_task, cronjob_manage, computer_use, manage_connections]'

"$HERMES_BIN" config set tools.tool_search.enabled on >/dev/null
"$HERMES_BIN" config set tools.tool_search.defer "$DEFER" >/dev/null
# Bare bridge: tool_search itself is the capability directory. Avoid embedding
# a per-turn catalog listing inside its schema.
"$HERMES_BIN" config set tools.tool_search.listing off >/dev/null
"$HERMES_BIN" config set tools.tool_search.listing_max_tokens 200 >/dev/null
"$HERMES_BIN" config set tools.tool_search.search_default_limit 4 >/dev/null
"$HERMES_BIN" config set tools.tool_search.max_search_limit 8 >/dev/null

# Native Hermes prompt switches. These are useful on large remote models but
# duplicate the compact router contract for a constrained local model. They do
# not remove tools or memory; they only remove always-on explanatory prose.
set_optional() {
  local key="$1" value="$2"
  if "$HERMES_BIN" config set "$key" "$value" >/dev/null 2>&1; then
    printf '[compact-prompt] set %s=%s\n' "$key" "$value"
  else
    printf '[compact-prompt] skipped unsupported key %s\n' "$key"
  fi
}

set_optional agent.task_completion_guidance false
set_optional agent.parallel_tool_call_guidance false
set_optional agent.tool_use_enforcement false
set_optional agent.execution_guidance false
set_optional agent.environment_probe false
set_optional agent.bot_mode_protocol false

# Keep memory + USER profile enabled: together they are only ~2 KB and are
# valuable persistent context. Keep the user's SOUL/identity untouched.

systemctl --user restart hermes-gateway.service 2>/dev/null || "$HERMES_BIN" gateway restart || true

echo
echo '=== CLI prompt after compact profile ==='
"$HERMES_BIN" prompt-size || true

echo
echo '=== Telegram prompt after compact profile ==='
"$HERMES_BIN" prompt-size --platform telegram || true

if [[ -f "$SCRIPT_DIR/diagnose-router.sh" ]]; then
  echo
echo '=== Router diagnostic ==='
  bash "$SCRIPT_DIR/diagnose-router.sh" || true
fi

echo
echo "Compact local prompt enabled. Backup: $BACKUP"
echo "Do not run an LLM test yet; compare the prompt-size output first."
