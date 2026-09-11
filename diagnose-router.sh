#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Run diagnose-router.sh as the Hermes user, not root." >&2
  exit 1
fi

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export HERMES_HOME
SRC="$HERMES_HOME/hermes-agent"
PY="$SRC/venv/bin/python"

[[ -x "$PY" ]] || { echo "Missing Hermes Python: $PY" >&2; exit 1; }
[[ -d "$SRC" ]] || { echo "Missing Hermes source: $SRC" >&2; exit 1; }

cd "$SRC"

"$PY" - <<'PY'
import json
import os
import sys
from pathlib import Path

home = Path(os.environ.get("HERMES_HOME", Path.home()/".hermes"))
src = home / "hermes-agent"
sys.path.insert(0, str(src))

print("=== Hermes Smart Router diagnostic ===")
print(f"source={src}")

try:
    from hermes_cli.config import load_config
    cfg = load_config() or {}
except Exception as exc:
    print(f"CONFIG_ERROR={type(exc).__name__}: {exc}")
    raise SystemExit(2)

raw_ts = ((cfg.get("tools") or {}).get("tool_search")) if isinstance(cfg.get("tools"), dict) else None
print("\n[config tools.tool_search]")
print(json.dumps(raw_ts, ensure_ascii=False, indent=2, default=str))

try:
    from tools import tool_search as ts
    annotations = getattr(ts.ToolSearchConfig, "__annotations__", {}) or {}
    supports_core_defer = "defer_tools" in annotations or hasattr(ts.ToolSearchConfig, "effective_defer_tools")
    print("\n[installed tool_search implementation]")
    print(f"module={getattr(ts, '__file__', '?')}")
    print(f"supports_core_defer={supports_core_defer}")
    resolved = ts.load_config()
    print(f"resolved_enabled={getattr(resolved, 'enabled', None)}")
    print(f"resolved_defer={sorted(getattr(resolved, 'effective_defer_tools', []) or [])}")
except Exception as exc:
    print(f"TOOL_SEARCH_ERROR={type(exc).__name__}: {exc}")
    supports_core_defer = False

try:
    from hermes_cli.tools_config import _get_platform_tools
    import model_tools
except Exception as exc:
    print(f"IMPORT_ERROR={type(exc).__name__}: {exc}")
    raise SystemExit(3)


def tool_name(td):
    if not isinstance(td, dict):
        return ""
    fn = td.get("function")
    return str(fn.get("name", "")) if isinstance(fn, dict) else str(td.get("name", ""))


def byte_size(defs):
    return len(json.dumps(defs, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

for platform in ("cli", "telegram"):
    try:
        enabled = sorted(_get_platform_tools(cfg, platform))
    except Exception as exc:
        print(f"\n[{platform}] platform resolution failed: {exc}")
        continue

    raw_defs = model_tools.get_tool_definitions(
        enabled_toolsets=enabled,
        quiet_mode=True,
        skip_tool_search_assembly=True,
    ) or []
    assembled_defs = model_tools.get_tool_definitions(
        enabled_toolsets=enabled,
        quiet_mode=True,
    ) or []

    raw_names = [tool_name(x) for x in raw_defs]
    assembled_names = [tool_name(x) for x in assembled_defs]
    deferred = [n for n in raw_names if n and n not in assembled_names]
    bridge = [n for n in assembled_names if n in {"tool_search", "tool_describe", "tool_call"}]

    print(f"\n[{platform}]")
    print(f"enabled_toolsets={enabled}")
    print(f"raw_count={len(raw_defs)} raw_schema_bytes={byte_size(raw_defs)}")
    print(f"assembled_count={len(assembled_defs)} assembled_schema_bytes={byte_size(assembled_defs)}")
    print(f"bridge_tools={bridge}")
    print(f"deferred_count={len(deferred)}")
    print("assembled_names=" + ",".join(assembled_names))

print("\n[result]")
if not supports_core_defer:
    print("ROUTER_STATUS=UNSUPPORTED_INSTALLED_BUILD")
    print("The installed Hermes build does not expose the current core-tool defer mechanism.")
else:
    print("ROUTER_STATUS=CHECK_COUNTS_ABOVE")
    print("If assembled_schema_bytes is far below raw_schema_bytes and bridge_tools are present, routing is active even if hermes prompt-size reports the raw catalog.")
PY
