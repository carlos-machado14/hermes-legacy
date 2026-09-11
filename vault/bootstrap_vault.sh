#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Run as the Hermes user, not root." >&2
  exit 1
fi

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
VAULT="${OBSIDIAN_VAULT_PATH:-$HERMES_HOME/vault}"
ENV_FILE="$HERMES_HOME/.env"
SKILL_DIR="$HERMES_HOME/skills/hermes-local-memory"

mkdir -p "$HERMES_HOME" "$VAULT" "$SKILL_DIR"
mkdir -p \
  "$VAULT/00-Inbox" \
  "$VAULT/10-Memory" \
  "$VAULT/20-Projects" \
  "$VAULT/30-Routines" \
  "$VAULT/40-Knowledge" \
  "$VAULT/50-Decisions" \
  "$VAULT/60-Daily" \
  "$VAULT/70-References" \
  "$VAULT/90-Archive" \
  "$VAULT/Templates"

upsert_env() {
  local key="$1" value="$2"
  touch "$ENV_FILE"
  chmod 600 "$ENV_FILE" 2>/dev/null || true
  if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    python3 - "$ENV_FILE" "$key" "$value" <<'PY'
import sys
from pathlib import Path
p=Path(sys.argv[1]); key=sys.argv[2]; value=sys.argv[3]
lines=p.read_text(encoding='utf-8').splitlines()
out=[]
done=False
for line in lines:
    if line.startswith(key+'='):
        if not done:
            out.append(f'{key}={value}')
            done=True
    else:
        out.append(line)
if not done:
    out.append(f'{key}={value}')
p.write_text('\n'.join(out).rstrip()+'\n',encoding='utf-8')
PY
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

upsert_env OBSIDIAN_VAULT_PATH "$VAULT"

if [[ ! -f "$VAULT/Home.md" ]]; then
cat > "$VAULT/Home.md" <<'EOF'
# Hermes Knowledge Vault

Este vault é a base de conhecimento legível por humanos do Hermes.

## Áreas
- [[00-Inbox]] — captura rápida
- [[10-Memory]] — fatos duráveis e contexto operacional
- [[20-Projects]] — projetos ativos
- [[30-Routines]] — rotinas, automações e runbooks
- [[40-Knowledge]] — conhecimento consolidado
- [[50-Decisions]] — decisões e ADRs
- [[60-Daily]] — registros diários
- [[70-References]] — referências externas
- [[90-Archive]] — material arquivado

A memória interna do Hermes continua existindo. O vault complementa essa memória com documentação estruturada, auditável e fácil de abrir no Obsidian.
EOF
fi

if [[ ! -f "$VAULT/Templates/Decision.md" ]]; then
cat > "$VAULT/Templates/Decision.md" <<'EOF'
---
type: decision
status: active
created: {{date}}
---
# Decisão: 

## Contexto

## Decisão

## Consequências

## Relacionados
EOF
fi

if [[ ! -f "$VAULT/Templates/Project.md" ]]; then
cat > "$VAULT/Templates/Project.md" <<'EOF'
---
type: project
status: active
created: {{date}}
---
# Projeto: 

## Objetivo

## Estado atual

## Próximos passos

## Decisões

## Referências
EOF
fi

cat > "$SKILL_DIR/SKILL.md" <<'EOF'
---
name: hermes-local-memory
description: Organize durable project knowledge, decisions, routines and operational context in the local Obsidian-compatible Hermes vault.
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [memory, obsidian, vault, local-only, knowledge]
    related_skills: [obsidian]
---

# Hermes Local Knowledge Memory

Use this skill when information should remain useful beyond the current conversation, especially project state, architecture decisions, operational procedures, recurring routines, lessons learned, and curated reference material.

The vault path is `OBSIDIAN_VAULT_PATH`. Resolve it to an absolute path before file operations.

## Storage policy

- `00-Inbox/`: raw captures that still need organization.
- `10-Memory/`: durable operational facts and concise reusable context.
- `20-Projects/`: one note or folder per active project.
- `30-Routines/`: routine definitions, runbooks, dependencies, failure notes.
- `40-Knowledge/`: consolidated reusable knowledge.
- `50-Decisions/`: architecture/product decisions and their rationale.
- `60-Daily/`: dated execution logs only when a daily record is useful.
- `70-References/`: stable references and source notes.
- `90-Archive/`: inactive material.

Prefer updating an existing canonical note over creating duplicates. Use `[[wikilinks]]` between related notes.

Do not store passwords, API keys, tokens, private keys or raw credentials in the vault. Do not dump whole conversations. Distill only information that is likely to remain useful.

Hermes' built-in persistent memory remains the fast personal/context memory. The vault is the structured, auditable knowledge layer.
EOF

printf 'vault=%s\n' "$VAULT"
printf 'skill=%s\n' "$SKILL_DIR/SKILL.md"
