#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# O repositório pode ser clonado com scripts 0644 e executados via `bash update.sh`.
# Não trate apenas mudança de bit executável (chmod +x) como alteração de conteúdo.
git config core.fileMode false

if ! git diff --quiet --ignore-submodules -- . || ! git diff --cached --quiet --ignore-submodules -- .; then
  echo "Existem alteracoes locais de CONTEUDO em arquivos versionados." >&2
  echo "O updater nao vai sobrescreve-las." >&2
  echo >&2
  git status --short >&2 || true
  echo >&2
  echo "Se esta VPS usa o repo apenas como checkout e seus dados ficam em ~/.hermes/," >&2
  echo "voce pode limpar somente arquivos versionados com:" >&2
  echo "  git reset --hard HEAD" >&2
  echo "Depois rode novamente: bash update.sh" >&2
  exit 2
fi

printf '\n=== Hermes safe update ===\n'
git pull --ff-only

# Não precisamos alterar o modo dos arquivos no checkout; execute com bash.
bash upgrade-autonomous.sh

echo
echo "Atualizacao concluida sem migrar ou substituir dados pessoais."
