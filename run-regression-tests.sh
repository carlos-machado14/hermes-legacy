#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIVE=0
[[ "${1:-}" == "--live" ]] && LIVE=1

echo "== Hermes regression: unit contracts =="
python3 -m unittest discover -s "$ROOT/tests" -p 'test_*.py' -v

if [[ "$LIVE" != "1" ]]; then
  echo
  echo "Unit contracts OK. Use '$0 --live' on the VPS for runtime smoke tests."
  exit 0
fi

CORE="$HOME/.hermes/core-v2"
PY="$CORE/venv/bin/python"

[[ -x "$PY" ]] || { echo "Core venv not found: $PY" >&2; exit 1; }
[[ -f "$CORE/core_entry.py" ]] || { echo "core_entry.py not found" >&2; exit 1; }

echo
echo "== Live 1/4: local model =="
curl -fsS --max-time 10 http://127.0.0.1:8088/v1/models >/dev/null
echo "LLM ready"

echo
echo "== Live 2/4: deterministic fast path =="
START="$(date +%s%3N)"
OUT="$(timeout 5s "$PY" "$CORE/core_entry.py" 'Responda apenas: REGRESSION_OK')"
END="$(date +%s%3N)"
[[ "$OUT" == "REGRESSION_OK" ]] || { echo "Unexpected: $OUT" >&2; exit 1; }
echo "OK $((END-START))ms"

echo
echo "== Live 3/4: normal conversation =="
START="$(date +%s%3N)"
OUT="$(timeout 30s "$PY" "$CORE/core_entry.py" 'Qual é a capital da Itália?')"
END="$(date +%s%3N)"
[[ -n "$OUT" ]] || { echo "No response from core" >&2; exit 1; }
echo "OK $((END-START))ms :: ${OUT:0:160}"

echo
echo "== Live 4/4: plugin registration =="
hermes plugins doctor "$HOME/.hermes/plugins/hermes-core-fastpath" --ci

echo
echo "All regression checks passed."
echo "Telemetry: $CORE/logs/perf.jsonl"
