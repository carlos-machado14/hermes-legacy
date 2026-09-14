#!/usr/bin/env bash
set -Eeuo pipefail

LOG="${HERMES_PERF_LOG:-$HOME/.hermes/core-v2/logs/perf.jsonl}"
LIMIT="${1:-250}"

[[ -f "$LOG" ]] || { echo "Telemetry log not found: $LOG" >&2; exit 1; }

python3 - "$LOG" "$LIMIT" <<'PY'
from __future__ import annotations
import json, statistics, sys
from collections import defaultdict
from pathlib import Path

path = Path(sys.argv[1])
limit = max(1, int(sys.argv[2]))
rows = []
for line in path.read_text(encoding='utf-8').splitlines()[-limit:]:
    try:
        item = json.loads(line)
    except Exception:
        continue
    if isinstance(item, dict):
        rows.append(item)

def pct(values, p):
    values = sorted(values)
    if not values:
        return 0.0
    idx = int(round((len(values)-1) * p))
    return float(values[max(0, min(idx, len(values)-1))])

by_stage = defaultdict(list)
for row in rows:
    value = row.get('elapsed_ms')
    if isinstance(value, (int, float)):
        by_stage[str(row.get('stage') or '?')].append(float(value))

print(f'Hermes performance — last {len(rows)} telemetry events')
print()
print(f"{'stage':26} {'n':>5} {'avg':>10} {'p50':>10} {'p95':>10} {'max':>10}")
print('-' * 76)
for stage, values in sorted(by_stage.items()):
    print(f"{stage:26} {len(values):5d} {statistics.fmean(values):10.1f} {pct(values,.50):10.1f} {pct(values,.95):10.1f} {max(values):10.1f}")

print('\nRecent completed traces:')
completed = [r for r in rows if r.get('stage') == 'core.total'][-10:]
for row in completed:
    print(
        f"- {row.get('trace_id','?')} | {row.get('tier','?'):7} | "
        f"{float(row.get('elapsed_ms') or 0):8.1f} ms | route={row.get('route','?')} | "
        f"in={row.get('input_chars','?')} out={row.get('output_chars','?')}"
    )
PY
