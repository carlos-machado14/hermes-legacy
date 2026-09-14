#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE / "apply_realtime_and_natural_cron.py"

spec = importlib.util.spec_from_file_location("hermes_realtime_patch_v1", BASE)
if spec is None or spec.loader is None:
    raise SystemExit(f"could not load patch module: {BASE}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def insert_flexible(path: Path, marker: str, block: str) -> None:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        print(f"[skip] {path.name}: patch already applied")
        return

    needle = "\nif __name__ == '__main__':\n"
    rendered = "\n" + block.rstrip() + "\n"
    if needle in text:
        text = text.replace(needle, rendered + needle, 1)
    else:
        text = text.rstrip() + rendered + "\n"

    path.write_text(text, encoding="utf-8")
    print(f"[ok] {path.name}")


mod.insert_before_main = insert_flexible
raise SystemExit(mod.main())
