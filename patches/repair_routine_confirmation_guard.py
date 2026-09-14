#!/usr/bin/env python3
from __future__ import annotations

import subprocess
from pathlib import Path

CRON = Path.home() / ".hermes" / "core-v2" / "cron_manager.py"
MARKER = "# HERMES_ROUTINE_CONFIRMATION_V1"


def main() -> int:
    if not CRON.exists():
        raise SystemExit(f"missing runtime file: {CRON}")

    text = CRON.read_text(encoding="utf-8")
    marker_pos = text.find(MARKER)
    if marker_pos < 0:
        raise SystemExit("routine confirmation patch marker not found")

    guards = [
        '\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
        "\nif __name__ == '__main__':\n    raise SystemExit(main())\n",
    ]

    repaired = False
    for guard in guards:
        pos = text.find(guard)
        if 0 <= pos < marker_pos:
            text = text.replace(guard, "\n# main guard deferred by routine confirmation repair\n", 1)
            repaired = True
            break

    if not any(g in text[marker_pos:] for g in guards):
        text = text.rstrip() + '\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
        repaired = True

    if repaired:
        CRON.write_text(text, encoding="utf-8")
        print(f"[ok] repaired execution order in {CRON}")
    else:
        print(f"[skip] execution order already correct in {CRON}")

    py = str(Path.home() / ".hermes" / "core-v2" / "venv" / "bin" / "python")
    subprocess.run([py, "-m", "py_compile", str(CRON)], check=True)
    help_run = subprocess.run([py, str(CRON), "--help"], text=True, capture_output=True, check=False)
    help_text = (help_run.stdout or "") + (help_run.stderr or "")
    if "--chat-key" not in help_text:
        raise SystemExit("ERRO: cron_manager.py ainda não reconhece --chat-key após o reparo")

    print("OK: cron_manager.py reconhece --chat-key e o fluxo conversacional está ativo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
