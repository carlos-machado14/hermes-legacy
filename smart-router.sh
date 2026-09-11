#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Run smart-router.sh as the Hermes user, not root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export HERMES_HOME
HERMES_BIN="${HERMES_BIN:-$(command -v hermes || true)}"
[[ -n "$HERMES_BIN" ]] || { echo "Hermes CLI not found" >&2; exit 1; }
[[ -f "$HERMES_HOME/config.yaml" ]] || { echo "Missing $HERMES_HOME/config.yaml" >&2; exit 1; }

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$HERMES_HOME/backups/smart-router-$STAMP"
SKILL_DIR="$HERMES_HOME/skills/hermes-smart-router"
mkdir -p "$BACKUP" "$SKILL_DIR"
cp -a "$HERMES_HOME/config.yaml" "$BACKUP/config.yaml"
[[ -f "$SKILL_DIR/SKILL.md" ]] && cp -a "$SKILL_DIR/SKILL.md" "$BACKUP/SKILL.md" || true

echo "[smart-router] backup=$BACKUP"

# Keep only a tiny ambient surface. Everything expensive should be discoverable
# through Hermes' progressive-disclosure bridge. Include both old and new tool
# names because this repo supports the user's August build and newer upstream.
# clarify intentionally stays direct because upstream A/B tests found that
# deferring it hurts the model's ability to ask for missing information.
DEFER='[web_search, web_extract, terminal, process, process_manage, read_file, write_file, patch, search_files, vision_analyze, image_generate, skills_list, skill_view, skill_manage, browser_exec, text_to_speech, todo, todo_list, memory, session_search, execute_code, delegate_task, cronjob_manage, computer_use, manage_connections]'

"$HERMES_BIN" config set tools.tool_search.enabled on >/dev/null
"$HERMES_BIN" config set tools.tool_search.defer "$DEFER" >/dev/null
"$HERMES_BIN" config set tools.tool_search.threshold_pct 3 >/dev/null
"$HERMES_BIN" config set tools.tool_search.listing on >/dev/null
"$HERMES_BIN" config set tools.tool_search.listing_max_tokens 1200 >/dev/null
"$HERMES_BIN" config set tools.tool_search.search_default_limit 4 >/dev/null
"$HERMES_BIN" config set tools.tool_search.max_search_limit 8 >/dev/null

# Clean up only the router prompt written by the first experimental revision.
# Never remove a pre-existing/user-owned prompt.
OLD_PROMPT="$("$HERMES_BIN" config get agent.system_prompt 2>/dev/null || true)"
if [[ "$OLD_PROMPT" == \[HERMES_LOCAL_SMART_ROUTER\]* ]]; then
  "$HERMES_BIN" config unset agent.system_prompt >/dev/null 2>&1 || true
fi

# The routing contract lives in a skill, not agent.system_prompt. Keeping it here
# avoids inflating every turn and avoids changing any user-owned personality or
# system-prompt configuration.
cat > "$SKILL_DIR/SKILL.md" <<'EOF'
---
name: hermes-smart-router
description: Route each request to the smallest relevant Hermes skill or capability, keeping local-model prompts small and actions reliable.
version: 1.2.0
platforms: [linux]
metadata:
  hermes:
    tags: [router, skills, tools, local-model, performance]
    related_skills: [hermes-local-memory]
---

# Hermes Smart Router

Use this routing policy whenever a request may require a skill, tool, persistent context, or external state.

## Core rule

Do not load capabilities speculatively. Start from the user's request and expose only the smallest capability set that can complete it.

## Routing order

1. **Direct answer** — general knowledge, explanation, writing, reasoning, or conversation that needs no external state: answer without tools.
2. **Skill first** — when an installed skill clearly matches the domain, use that skill's workflow instead of inventing a new one.
3. **Capability discovery** — when an action or external state is required, use `tool_search` or an exact listed capability name.
4. **Schema on demand** — load only the required tool schema with `tool_describe`.
5. **Execute** — call it through `tool_call` and inspect the result before loading another capability.
6. **Persist selectively** — durable decisions/project state go through `hermes-local-memory`; secrets never go to memory or the vault.

## Capability map

- current/public information -> web search/extract
- files/repositories/code -> file, terminal, code execution, relevant coding skill
- websites requiring interaction -> browser
- previous conversations -> session search
- durable personal/project context -> memory / hermes-local-memory
- scheduled or recurring actions -> cronjob
- long/isolated subtask -> delegation, only when the benefit exceeds the extra local-model call
- images -> vision or image generation
- missing required input -> clarify

## Small-model discipline

- Never load every tool for convenience.
- Prefer one capability family at a time.
- Avoid delegation for simple tasks: every child is another local inference.
- Avoid repeated searches when an earlier result is sufficient.
- Keep outputs concise unless the user requests depth.
- Reuse existing project/vault notes rather than creating duplicates.
EOF

systemctl --user restart hermes-gateway.service 2>/dev/null || "$HERMES_BIN" gateway restart || true

echo
printf 'tool_search.enabled='; "$HERMES_BIN" config get tools.tool_search.enabled || true
printf 'tool_search.defer='; "$HERMES_BIN" config get tools.tool_search.defer || true
printf 'router_skill=%s\n' "$SKILL_DIR/SKILL.md"
echo

if [[ -f "$SCRIPT_DIR/diagnose-router.sh" ]]; then
  bash "$SCRIPT_DIR/diagnose-router.sh"
else
  echo "diagnose-router.sh not found; run git pull and retry."
fi

echo
echo "Smart Router configured. Backup: $BACKUP"
