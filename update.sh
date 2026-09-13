#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Existem alteracoes locais em arquivos versionados." >&2
  echo "O updater nao vai sobrescreve-las. Commit/stash/reverta antes de atualizar." >&2
  exit 2
fi

printf '\n=== Hermes safe update ===\n'
git pull --ff-only
chmod +x upgrade-autonomous.sh
./upgrade-autonomous.sh

echo
echo "Atualizacao concluida sem migrar ou substituir dados pessoais."
