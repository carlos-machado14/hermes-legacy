#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "=============================================="
echo " Hermes v4.8 — low latency + safe fastpath"
echo "=============================================="

chmod +x install-core-v2.sh install-gateway-fastpath-plugin.sh run-regression-tests.sh performance-report.sh

echo
echo "[1/4] Atualizando Hermes Core..."
./install-core-v2.sh

echo
echo "[2/4] Atualizando FastPath/Gateway..."
./install-gateway-fastpath-plugin.sh

echo
echo "[3/4] Rodando contratos de regressao..."
./run-regression-tests.sh

echo
echo "[4/4] Smoke test ao vivo..."
./run-regression-tests.sh --live

echo
echo "Hermes v4.8 aplicado com sucesso."
echo "Performance: ./performance-report.sh"
echo "Gateway logs: journalctl --user -u hermes-gateway.service -f"
echo "Core telemetry: tail -f ~/.hermes/core-v2/logs/perf.jsonl"
