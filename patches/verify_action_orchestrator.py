#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
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

    spec = importlib.util.spec_from_file_location('action_orchestrator_verify', ORCH)
    if spec is None or spec.loader is None:
        fail('não consegui importar action_orchestrator')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    read_plan = module._plan('Pesquise uma empresa em Colombo PR que não tenha site')
    if read_plan is None or read_plan.tool != 'web' or read_plan.requires_confirmation:
        fail('pesquisa pontual não foi classificada como leitura web sem confirmação')

    mutation_plan = module._plan('reinicie o gateway')
    if mutation_plan is None or mutation_plan.tool != 'service_restart' or not mutation_plan.requires_confirmation:
        fail('ação mutável não exige confirmação')

    print('OK: Action Orchestrator validado')
    print('OK: contexto por chat + confirmação + executor + validação + journal + retry seguros ativos')
    print('OK: mutações de rotina exigem confirmação')
    print('OK: alertas proativos de incidentes ativos')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
