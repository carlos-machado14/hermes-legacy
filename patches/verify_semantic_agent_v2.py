#!/usr/bin/env python3
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path.home() / '.hermes' / 'core-v2'
PY = ROOT / 'venv' / 'bin' / 'python'
CORE = ROOT / 'core_entry.py'
AGENT = ROOT / 'semantic_agent.py'
FAST = Path.home() / '.hermes' / 'plugins' / 'hermes-core-fastpath' / '__init__.py'


def fail(message: str) -> None:
    raise SystemExit('ERRO: ' + message)


def main() -> int:
    for path in (CORE, AGENT, FAST):
        if not path.exists():
            fail(f'arquivo ausente: {path}')

    core_text = CORE.read_text(encoding='utf-8')
    fast_text = FAST.read_text(encoding='utf-8')
    if '# HERMES_SEMANTIC_AGENT_V2' not in core_text or 'handle_semantic_agent(text, _original_llm)' not in core_text:
        fail('Semantic Agent V2 não está como cérebro primário no core_entry')
    if '# HERMES_SEMANTIC_AGENT_TIMEOUTS_V2' not in fast_text:
        fail('SLA do fastpath não foi atualizado')
    if "env['HERMES_CHAT_KEY'] = key" not in fast_text:
        fail('contexto por chat não está sendo propagado')

    check = subprocess.run(
        [str(PY), '-m', 'py_compile', str(CORE), str(AGENT), str(FAST)],
        text=True, capture_output=True, timeout=20,
    )
    if check.returncode != 0:
        fail((check.stderr or check.stdout or 'py_compile falhou')[-1800:])

    sys.path.insert(0, str(ROOT))
    agent = importlib.import_module('semantic_agent')

    def llm_research(*args, **kwargs):
        return '{"intent":"research","confidence":0.98,"goal":"achar uma empresa sem site","needs_tools":true,"capabilities":["web.search"],"requires_confirmation":false,"missing":[],"reason":"pesquisa pontual"}'

    routed = agent.interpret('Ache uma empresa em Colombo PR sem site', llm_research)
    if not routed or routed.get('intent') != 'research' or routed.get('requires_confirmation'):
        fail('pesquisa pontual não foi entendida semanticamente')

    def llm_bad_missing(*args, **kwargs):
        return '{"intent":"research","confidence":0.98,"goal":"achar um cliente potencial","needs_tools":true,"capabilities":["web.search"],"requires_confirmation":false,"missing":["tarefas pendentes","recursos locais"],"reason":"pesquisa"}'

    routed = agent.interpret('Quero encontrar um possível cliente aqui na região', llm_bad_missing)
    if not routed or routed.get('missing'):
        fail('semantic agent ainda repassa detalhes internos como missing')

    def llm_valid_missing(*args, **kwargs):
        return '{"intent":"research","confidence":0.98,"goal":"achar um cliente potencial","needs_tools":true,"capabilities":["web.search"],"requires_confirmation":false,"missing":["qual cidade ou região devo pesquisar"],"reason":"localização indispensável"}'

    routed = agent.interpret('Quero um cliente aqui na região', llm_valid_missing)
    if not routed or not routed.get('missing') or 'cidade' not in routed['missing'][0].casefold():
        fail('semantic agent removeu uma clarificação humana realmente necessária')

    def llm_cron_query(*args, **kwargs):
        return '{"intent":"cron_query","confidence":0.97,"goal":"verificar rotina existente","needs_tools":true,"capabilities":[],"requires_confirmation":false,"missing":[],"reason":"consulta"}'

    routed = agent.interpret('Já temos uma rotina pra isso?', llm_cron_query)
    if not routed or routed.get('intent') != 'cron_query':
        fail('consulta de rotina não foi reconhecida')

    def llm_action(*args, **kwargs):
        return '{"intent":"system_action","confidence":0.99,"goal":"reiniciar gateway","needs_tools":true,"capabilities":["system.inspect"],"requires_confirmation":true,"missing":[],"reason":"mutação"}'

    routed = agent.interpret('Reinicie o gateway', llm_action)
    if not routed or not routed.get('requires_confirmation'):
        fail('mutação não exige confirmação')

    print('OK: Semantic Agent V2 validado')
    print('OK: pesquisa pontual != cron; consulta de cron reconhecida; mutação exige confirmação')
    print('OK: detalhes internos nunca viram perguntas ao usuário; clarificações humanas essenciais são preservadas')
    print('OK: contexto por chat + SLA ampliado + fallback legado preservados')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
