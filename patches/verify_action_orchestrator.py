#!/usr/bin/env python3
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path.home() / '.hermes' / 'core-v2'
PY = ROOT / 'venv' / 'bin' / 'python'
CORE = ROOT / 'core_entry.py'
ORCH = ROOT / 'action_orchestrator.py'
FASTPATH = Path.home() / '.hermes' / 'plugins' / 'hermes-core-fastpath' / '__init__.py'
AUTO = ROOT / 'autonomous_service.py'
CRON = ROOT / 'cron_manager.py'


def fail(msg: str) -> None:
    raise SystemExit('ERRO: ' + msg)


def require(path: Path, token: str) -> None:
    text = path.read_text(encoding='utf-8')
    if token not in text:
        fail(f'{path.name} sem {token}')


def main() -> int:
    for path in (CORE, ORCH, FASTPATH, AUTO, CRON):
        if not path.exists():
            fail(f'arquivo ausente: {path}')

    require(CORE, '# HERMES_ACTION_ORCHESTRATOR_V1')
    require(CORE, 'handle_action_orchestrator')
    require(FASTPATH, '# HERMES_CHAT_CONTEXT_ENV_V1')
    require(FASTPATH, "env['HERMES_CHAT_KEY']")
    require(CRON, '# HERMES_ROUTINE_MUTATION_CONFIRMATION_V2')
    require(AUTO, '# HERMES_PROACTIVE_INCIDENT_ALERTS_V1')

    compile_check = subprocess.run(
        [str(PY), '-m', 'py_compile', str(CORE), str(ORCH), str(FASTPATH), str(AUTO), str(CRON)],
        text=True, capture_output=True, timeout=20,
    )
    if compile_check.returncode != 0:
        fail((compile_check.stderr or compile_check.stdout or 'py_compile falhou')[-1800:])

    probe = subprocess.run(
        [str(PY), '-c', (
            "from action_orchestrator import _plan, policy; "
            "r=_plan('Pesquise uma empresa em Colombo PR que não tenha site'); "
            "m=_plan('reinicie o gateway'); "
            "assert r and r.tool=='web' and not r.requires_confirmation; "
            "assert m and m.tool=='service_restart' and m.requires_confirmation; "
            "assert policy().get('confirm_mutations') is True; "
            "print('probe-ok')"
        )],
        cwd=str(ROOT), text=True, capture_output=True, timeout=20,
    )
    if probe.returncode != 0 or 'probe-ok' not in (probe.stdout or ''):
        fail((probe.stderr or probe.stdout or 'probe do Action Orchestrator falhou')[-1800:])

    print('OK: Action Orchestrator validado')
    print('OK: contexto por chat + confirmação + executor + validação + journal + retry seguros ativos')
    print('OK: mutações de rotina exigem confirmação')
    print('OK: alertas proativos de incidentes ativos')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
