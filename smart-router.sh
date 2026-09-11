#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Run smart-router.sh as the Hermes user, not root." >&2
  exit 1
fi

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

# Keep only a tiny ambient surface. Everything expensive is discoverable through
# Hermes' native progressive-disclosure bridge (tool_search/tool_describe/tool_call).
# clarify intentionally stays direct because upstream A/B tests found that deferring
# it hurts the model's ability to ask a user for missing information.
DEFER='[web_search, web_extract, terminal, process_manage, read_file, write_file, patch, search_files, vision_analyze, image_generate, skills_list, skill_view, skill_manage, browser_exec, text_to_speech, todo_list, memory, session_search, execute_code, delegate_task, cronjob_manage, computer_use, manage_connections]'

"$HERMES_BIN" config set tools.tool_search.enabled on >/dev/null
"$HERMES_BIN" config set tools.tool_search.defer "$DEFER" >/dev/null
"$HERMES_BIN" config set tools.tool_search.threshold_pct 3 >/dev/null
"$HERMES_BIN" config set tools.tool_search.listing on >/dev/null
"$HERMES_BIN" config set tools.tool_search.listing_max_tokens 1200 >/dev/null
"$HERMES_BIN" config set tools.tool_search.search_default_limit 4 >/dev/null
"$HERMES_BIN" config set tools.tool_search.max_search_limit 8 >/dev/null

# A compact always-on routing contract. It does not replace Hermes' normal system
# prompt; it tells the local model how to use progressive disclosure reliably.
ROUTER_PROMPT='Local capability routing: answer directly when no external state or action is required. For actions, current data, files, terminal, browser, memory, automation, code execution, vision, or session recall, do not guess and do not preload unrelated capabilities. Use tool_search/tool_describe/tool_call to load only the smallest relevant capability. Prefer an installed skill when its domain matches the request, then load only the tools that skill actually needs. For multi-step work, load capabilities sequentially rather than all at once. Ask a clarification only when a required input is missing. Persist durable project knowledge through the local memory/vault skill; never persist secrets.'
"$HERMES_BIN" config set agent.system_prompt "$ROUTER_PROMPT" >/dev/null

cat > "$SKILL_DIR/SKILL.md" <<'EOF'
---
name: hermes-smart-router
description: Route each request to the smallest relevant Hermes skill or capability, keeping local-model prompts small and actions reliable.
version: 1.0.0
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

echo '[smart-router] prompt-size after routing:'
"$HERMES_BIN" prompt-size || true

echo
echo "Smart Router enabled. Backup: $BACKUP"
