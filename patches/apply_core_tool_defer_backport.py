#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
TARGET = HERMES_HOME / "hermes-agent" / "tools" / "tool_search.py"
MARKER = "HERMES_LOCAL_CORE_DEFER_BACKPORT"


def die(msg: str) -> None:
    print(f"[core-defer-backport] ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        die(f"expected exactly one match for {label}, found {count}; refusing blind patch")
    return text.replace(old, new, 1)


if not TARGET.is_file():
    die(f"missing {TARGET}")

src = TARGET.read_text(encoding="utf-8")

# Newer upstream Hermes already supports an explicit defer list. Do not modify it.
if "defer_tools: Optional[frozenset]" in src and "effective_defer_tools" in src:
    print("[core-defer-backport] native core defer support already present; no patch needed")
    raise SystemExit(0)

if MARKER in src:
    print("[core-defer-backport] backport already applied")
    raise SystemExit(0)

# Fail closed unless this looks like the older implementation we inspected.
required = [
    "class ToolSearchConfig:",
    "def is_deferrable_tool_name(name: str) -> bool:",
    "def classify_tools(tool_defs: List[Dict[str, Any]])",
    "visible, deferrable = classify_tools(incoming)",
    "def dispatch_tool_search(",
    "def dispatch_tool_describe(",
    "def scoped_deferrable_names(",
    "def resolve_underlying_call(",
]
missing = [x for x in required if x not in src]
if missing:
    die("installed tool_search.py does not match the supported old layout: " + ", ".join(missing))

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup_dir = HERMES_HOME / "backups" / f"core-defer-backport-{stamp}"
backup_dir.mkdir(parents=True, exist_ok=True)
backup = backup_dir / "tool_search.py"
shutil.copy2(TARGET, backup)
print(f"[core-defer-backport] backup={backup}")

# 1) Extend the old config model with an explicit defer list.
src = replace_once(
    src,
    "    listing_max_tokens: int = 4000\n\n    @classmethod",
    "    listing_max_tokens: int = 4000\n"
    "    # Backport: an explicit list may defer selected core tools.\n"
    "    defer_tools: Optional[frozenset] = None\n\n"
    "    @property\n"
    "    def effective_defer_tools(self) -> frozenset:\n"
    "        return frozenset() if self.defer_tools is None else self.defer_tools\n\n"
    "    @classmethod",
    "ToolSearchConfig.defer_tools",
)

src = replace_once(
    src,
    "        listing_max_tokens = max(200, min(60000, _safe_int(raw.get(\"listing_max_tokens\"), 4000)))\n\n        return cls(",
    "        listing_max_tokens = max(200, min(60000, _safe_int(raw.get(\"listing_max_tokens\"), 4000)))\n"
    "        defer_raw = raw.get(\"defer\")\n\n"
    "        return cls(",
    "parse defer list",
)

src = replace_once(
    src,
    "            listing=listing,\n            listing_max_tokens=listing_max_tokens,\n        )",
    "            listing=listing,\n"
    "            listing_max_tokens=listing_max_tokens,\n"
    "            defer_tools=(frozenset(str(n).strip() for n in defer_raw if str(n).strip())\n"
    "                         if isinstance(defer_raw, (list, tuple, set)) else None),\n"
    "        )",
    "ToolSearchConfig return",
)

# 2) Allow explicitly named core tools to defer; preserve old plugin/MCP behavior.
src = replace_once(
    src,
    "def is_deferrable_tool_name(name: str) -> bool:",
    "def is_deferrable_tool_name(name: str, defer_tools: Optional[frozenset] = None) -> bool:",
    "is_deferrable signature",
)
src = replace_once(
    src,
    "    if name in BRIDGE_TOOL_NAMES:\n        return False\n    if name in _core_tool_names():",
    "    if name in BRIDGE_TOOL_NAMES:\n"
    "        return False\n"
    "    # Explicit user config wins over the old 'core tools never defer' rule.\n"
    "    if defer_tools is not None and name in defer_tools:\n"
    "        return True\n"
    "    if name in _core_tool_names():",
    "explicit core defer gate",
)

src = replace_once(
    src,
    "def classify_tools(tool_defs: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:",
    "def classify_tools(tool_defs: List[Dict[str, Any]], defer_tools: Optional[frozenset] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:",
    "classify signature",
)
src = src.replace("        if is_deferrable_tool_name(name):\n", "        if is_deferrable_tool_name(name, defer_tools):\n", 1)

# 3) Assembly must apply the configured defer list.
src = replace_once(
    src,
    "    visible, deferrable = classify_tools(incoming)",
    "    visible, deferrable = classify_tools(incoming, config.effective_defer_tools)",
    "assembly classification",
)

# 4) Bridge search/describe/call paths must use the same configured scope.
src = replace_once(
    src,
    "    _, deferrable = classify_tools(current_tool_defs)\n    catalog = build_catalog(deferrable)",
    "    _, deferrable = classify_tools(current_tool_defs, config.effective_defer_tools)\n"
    "    catalog = build_catalog(deferrable)",
    "dispatch_tool_search classification",
)

src = replace_once(
    src,
    "def dispatch_tool_describe(args: Dict[str, Any],\n                           *,\n                           current_tool_defs: List[Dict[str, Any]]) -> str:\n    \"\"\"Execute the ``tool_describe`` bridge tool. Returns a JSON string.\"\"\"\n    name = str(args.get(\"name\") or \"\").strip()",
    "def dispatch_tool_describe(args: Dict[str, Any],\n"
    "                           *,\n"
    "                           current_tool_defs: List[Dict[str, Any]]) -> str:\n"
    "    \"\"\"Execute the ``tool_describe`` bridge tool. Returns a JSON string.\"\"\"\n"
    "    config = load_config()\n"
    "    name = str(args.get(\"name\") or \"\").strip()",
    "dispatch_tool_describe config",
)

# Only the describe occurrence here should be replaced first; resolve_underlying is handled below.
src = replace_once(
    src,
    "    if not is_deferrable_tool_name(name):\n        return tool_error(\n            f\"'{name}' is not a deferrable tool. If you see it in the tools list \"",
    "    if not is_deferrable_tool_name(name, config.effective_defer_tools):\n"
    "        return tool_error(\n"
    "            f\"'{name}' is not a deferrable tool. If you see it in the tools list \"",
    "dispatch_tool_describe eligibility",
)

# After the describe guard the next classification is its catalog lookup.
needle = "    _, deferrable = classify_tools(current_tool_defs)\n    for td in deferrable:"
src = replace_once(
    src,
    needle,
    "    _, deferrable = classify_tools(current_tool_defs, config.effective_defer_tools)\n"
    "    for td in deferrable:",
    "dispatch_tool_describe classification",
)

# scoped_deferrable_names: same universe as configured bridge.
src = replace_once(
    src,
    "    names: set[str] = set()\n    for td in tool_defs:",
    "    names: set[str] = set()\n"
    "    defer_tools = load_config().effective_defer_tools\n"
    "    for td in tool_defs:",
    "scoped defer config",
)
src = replace_once(
    src,
    "        if name and is_deferrable_tool_name(name):\n            names.add(name)",
    "        if name and is_deferrable_tool_name(name, defer_tools):\n"
    "            names.add(name)",
    "scoped defer eligibility",
)

# resolve_underlying_call: permit configured core tools through the bridge.
src = replace_once(
    src,
    "    if not is_deferrable_tool_name(name):\n        return None, {}, (\n            f\"'{name}' is not a deferrable tool. If it appears in the model-facing tools \"",
    "    defer_tools = load_config().effective_defer_tools\n"
    "    if not is_deferrable_tool_name(name, defer_tools):\n"
    "        return None, {}, (\n"
    "            f\"'{name}' is not a deferrable tool. If it appears in the model-facing tools \"",
    "resolve_underlying eligibility",
)

# Marker makes the backport idempotent and easy to remove/identify.
src = src.replace(
    'logger = logging.getLogger("tools.tool_search")',
    'logger = logging.getLogger("tools.tool_search")\n# HERMES_LOCAL_CORE_DEFER_BACKPORT',
    1,
)

# Syntax safety before touching the installed source.
try:
    compile(src, str(TARGET), "exec")
except SyntaxError as exc:
    die(f"patched source failed compile: {exc}")

TARGET.write_text(src, encoding="utf-8")

# Functional probe in the installed source tree.
sys.path.insert(0, str(TARGET.parent.parent))
try:
    import importlib
    ts = importlib.import_module("tools.tool_search")
    cfg = ts.load_config()
    if not hasattr(cfg, "effective_defer_tools"):
        raise RuntimeError("effective_defer_tools missing after patch")
    if "terminal" not in cfg.effective_defer_tools:
        raise RuntimeError("config defer list did not resolve terminal")
except Exception as exc:
    shutil.copy2(backup, TARGET)
    die(f"functional import/config probe failed; restored backup: {exc}")

print("[core-defer-backport] PATCH OK")
print(f"[core-defer-backport] target={TARGET}")
print(f"[core-defer-backport] backup={backup}")
