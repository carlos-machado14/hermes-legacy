#!/usr/bin/env python3
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path.home() / '.hermes' / 'core-v2'
PY = ROOT / 'venv' / 'bin' / 'python'
CRON = ROOT / 'cron_manager.py'
FASTPATH = Path.home() / '.hermes' / 'plugins' / 'hermes-core-fastpath' / '__init__.py'


def fail(message: str) -> None:
    raise SystemExit('ERRO: ' + message)


def main() -> int:
    cron_text = CRON.read_text(encoding='utf-8')
    fast_text = FASTPATH.read_text(encoding='utf-8')

    required_cron = (
        '# HERMES_ROUTINE_CONFIRMATION_V1',
        "parser.add_argument('--chat-key', default='default')",
        'def handle(text: str, chat_key:',
        'PENDING_ROUTINES_FILE',
    )
    for token in required_cron:
        if token not in cron_text:
            fail(f'cron_manager.py sem suporte de confirmação: {token}')

    required_fast = (
        '# HERMES_PENDING_ROUTINE_ROUTING_V1',
        "'--chat-key', key",
        '_pending_cron_exists(key)',
    )
    for token in required_fast:
        if token not in fast_text:
            fail(f'fastpath sem roteamento de confirmação: {token}')

    check = subprocess.run(
        [str(PY), str(CRON), '--help'],
        text=True,
        capture_output=True,
        timeout=10,
    )
    help_text = (check.stdout or '') + '\n' + (check.stderr or '')
    if check.returncode != 0 or '--chat-key' not in help_text:
        fail('cron_manager.py não reconhece --chat-key após o patch')

    compile_check = subprocess.run(
        [str(PY), '-m', 'py_compile', str(CRON), str(FASTPATH)],
        text=True,
        capture_output=True,
        timeout=15,
    )
    if compile_check.returncode != 0:
        fail((compile_check.stderr or compile_check.stdout or 'falha no py_compile')[-1200:])

    print('OK: confirmação conversacional de rotinas validada (--chat-key ativo)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
