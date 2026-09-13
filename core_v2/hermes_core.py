#!/usr/bin/env python3
from __future__ import annotations
import json, os, subprocess, sys, time
from pathlib import Path
import httpx, psutil, yaml
from tools import run_tool, pretty
from planner import classify as classify_plan, execute as execute_plan, compact_for_llm
from memory_store import recent as memory_recent
from recovery_engine import recover_once, history as recovery_history
from tool_registry import call as call_tool, list_tools
from project_registry import public_summary as project_summary
from incident_store import recent_incidents

ROOT = Path(__file__).resolve().parent
CFG = ROOT / 'config.yaml'
if not CFG.exists():
    CFG = ROOT / 'config.example.yaml'

with CFG.open() as f:
    config = yaml.safe_load(f)

BASE_URL = config['llm']['base_url'].rstrip('/')
MODEL = config['llm']['model']
TIMEOUT = config['llm'].get('timeout_seconds', 120)
MAX_TOKENS = config['llm'].get('max_tokens', 320)

SERVICE_ALIASES = {
    'gateway': 'hermes-gateway.service',
    'router': 'hermes-fast-router.service',
    'llm': 'hermes-local-llm.service',
    'modelo': 'hermes-local-llm.service',
    'health': 'hermes-core-health.service',
    'monitor': 'hermes-core-health.service',
    'watcher': 'hermes-core-watchers.service',
    'watchers': 'hermes-core-watchers.service',
    'api': 'hermes-core-api.service',
}


def llm(prompt: str, system: str | None = None, max_tokens: int | None = None) -> str:
    system = system or ('Voce e Hermes Core, um agente local-first rodando na VPS. '
                        'Seja objetivo, nao invente resultados de ferramentas e priorize acoes deterministicas.')
    payload = {
        'model': MODEL,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0.2,
        'max_tokens': max_tokens or MAX_TOKENS,
    }
    timeout = httpx.Timeout(connect=5.0, read=float(TIMEOUT), write=10.0, pool=5.0)
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f'{BASE_URL}/chat/completions', json=payload)
        r.raise_for_status()
        return r.json()['choices'][0]['message']['content'].strip()


def system_health() -> dict:
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage('/')
    return {
        'cpu_percent': psutil.cpu_percent(interval=0.25),
        'ram_percent': vm.percent,
        'ram_available_mb': round(vm.available / 1024 / 1024),
        'swap_percent': swap.percent,
        'disk_percent': disk.percent,
        'load': [round(v, 2) for v in os.getloadavg()],
        'uptime_hours': round((time.time() - psutil.boot_time()) / 3600, 1),
    }


def service_state(name: str) -> str:
    try:
        p = subprocess.run(['systemctl', '--user', 'is-active', name], text=True, capture_output=True, timeout=4)
        return (p.stdout or p.stderr).strip() or 'unknown'
    except Exception:
        return 'unknown'


def local_status() -> dict:
    data = system_health()
    data['services'] = {
        'llm': service_state('hermes-local-llm.service'),
        'gateway': service_state('hermes-gateway.service'),
        'router': service_state('hermes-fast-router.service'),
        'health_monitor': service_state('hermes-core-health.service'),
        'watchers': service_state('hermes-core-watchers.service'),
        'core_api': service_state('hermes-core-api.service'),
    }
    try:
        with httpx.Client(timeout=3) as client:
            r = client.get(f'{BASE_URL}/models')
            data['llm_http'] = r.status_code
            data['llm_ready'] = r.status_code == 200
    except Exception as e:
        data['llm_http'] = None
        data['llm_ready'] = False
        data['llm_error'] = str(e)
    return data


def format_health(data: dict) -> str:
    services = data.get('services', {})
    required = ('llm', 'gateway', 'router', 'health_monitor', 'watchers', 'core_api')
    service_ok = all(services.get(k) == 'active' for k in required)
    overall = 'OK' if service_ok and data.get('llm_ready') else 'ATENCAO'
    return (
        f'Hermes VPS: {overall}\n'
        f"CPU: {data['cpu_percent']}% | RAM: {data['ram_percent']}% ({data['ram_available_mb']} MB livres) | "
        f"Swap: {data['swap_percent']}% | Disco: {data['disk_percent']}%\n"
        f"Load: {data['load']} | Uptime: {data['uptime_hours']}h\n"
        f"LLM: {services.get('llm')} | Gateway: {services.get('gateway')} | Router: {services.get('router')}\n"
        f"Health: {services.get('health_monitor')} | Watchers: {services.get('watchers')} | API: {services.get('core_api')}\n"
        f"LLM HTTP: {data.get('llm_http')} | Modelo pronto: {'sim' if data.get('llm_ready') else 'nao'}"
    )


def route(text: str) -> str:
    t = text.lower().strip()
    if any(k in t for k in ('status da vps', 'saude da vps', 'saúde da vps', 'verifique a vps', 'como esta a vps', 'como está a vps')) or t in {'status', 'health', '/health'}:
        return 'health'
    if any(k in t for k in ('servicos do hermes', 'serviços do hermes', 'status dos servicos', 'status dos serviços')):
        return 'services'
    if any(k in t for k in ('containers', 'docker ps', 'status do docker')):
        return 'docker'
    if any(k in t for k in ('status das crons', 'status da cron', 'cron status')):
        return 'cron_status'
    if any(k in t for k in ('listar crons', 'lista de crons', 'cron list')):
        return 'cron_list'
    if any(k in t for k in ('quais projetos', 'listar projetos', 'liste os projetos', 'meus projetos')):
        return 'projects'
    if any(k in t for k in ('incidentes', 'incidentes recentes', 'problemas recentes', 'falhas recentes')):
        return 'incidents'
    if 'logs do gateway' in t or 'log do gateway' in t:
        return 'gateway_logs'
    if 'logs do llm' in t or 'log do llm' in t or 'logs do modelo' in t:
        return 'llm_logs'
    if 'logs do router' in t or 'log do router' in t:
        return 'router_logs'
    return 'llm'


def _report_text(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False).lower()


def deterministic_diagnosis(plan_name: str, report: dict) -> str | None:
    text = _report_text(report)
    if plan_name == 'diagnose_crons':
        if 'non-streaming api call timed out' in text or 'timed out after 900s' in text or 'provider timeout' in text:
            return ('Diagnostico rapido:\n- Causa: as crons falharam por timeout durante chamada ao modelo/API.\n'
                    '- O scheduler esta ativo; a falha foi de execucao.\n'
                    '- As crons locais no-agent evitam esse gargalo.')
        if 'failed' in text and 'cron' in text:
            return ('Diagnostico rapido:\n- Existem crons com falha registrada.\n'
                    '- O scheduler respondeu; consulte a ultima execucao e os logs para a causa especifica.')
        if 'gateway is running' in text and 'active job' in text:
            return ('Diagnostico rapido:\n- Scheduler e gateway estao ativos.\n'
                    '- Nao encontrei um padrao de erro conhecido nas evidencias coletadas.')
    if plan_name == 'diagnose_services':
        if 'inactive' in text or 'failed' in text:
            return 'Diagnostico rapido: ha pelo menos um servico inativo ou com falha.'
        if 'active' in text:
            return 'Diagnostico rapido: os servicos principais estao ativos.'
    return None


def diagnose_with_plan(text: str, plan_name: str) -> str:
    report = execute_plan(plan_name)
    fast = deterministic_diagnosis(plan_name, report)
    if fast:
        return fast
    evidence = compact_for_llm(report, max_chars=2200)
    prompt = ('Analise somente as evidencias reais abaixo. Responda em portugues em no maximo 5 linhas: '
              'causa provavel, evidencia principal e proxima acao segura. Nao invente dados.\n\n'
              f'Pedido: {text}\nEvidencias:\n{evidence}')
    try:
        return llm(prompt, max_tokens=120)
    except Exception:
        return 'Diagnostico coletado, mas o LLM nao respondeu. Evidencias:\n' + pretty(report)


def _format_history(rows: list[dict]) -> str:
    if not rows:
        return 'Nenhuma acao de recuperacao registrada ainda.'
    out = ['Historico operacional recente:']
    for item in rows[-10:]:
        stamp = time.strftime('%d/%m %H:%M', time.localtime(int(item.get('ts', 0))))
        status = 'OK' if item.get('ok') is True else ('FALHA' if item.get('ok') is False else '-')
        out.append(f"- {stamp} [{status}] {item.get('summary', item.get('kind', 'evento'))}")
    return '\n'.join(out)


def _format_projects() -> str:
    projects = project_summary()
    if not projects:
        return 'Nenhum projeto cadastrado ainda. Use a API local POST /projects para cadastrar.'
    out = ['Projetos cadastrados:']
    for p in projects:
        parts = [str(p.get('name'))]
        if p.get('health_url'):
            parts.append(f"health={p['health_url']}")
        if p.get('services'):
            parts.append(f"servicos={len(p['services'])}")
        out.append('- ' + ' | '.join(parts))
    return '\n'.join(out)


def _format_incidents() -> str:
    rows = recent_incidents(10)
    if not rows:
        return 'Nenhum incidente registrado.'
    out = ['Incidentes recentes:']
    for item in rows:
        stamp = time.strftime('%d/%m %H:%M', time.localtime(int(item.get('ts', 0))))
        out.append(f"- {stamp} [{item.get('severity', 'warning')}] {item.get('summary', 'incidente')}")
    return '\n'.join(out)


def _safe_direct_action(text: str) -> str | None:
    t = text.lower().strip()
    if any(k in t for k in ('corrija tudo', 'corrigir tudo', 'recupere os servicos', 'recupere os serviços', 'auto recovery', 'auto-recovery')):
        report = recover_once()
        return 'Recovery executado:\n' + pretty(report)
    if any(k in t for k in ('o que voce corrigiu', 'o que você corrigiu', 'historico de correcoes', 'histórico de correções', 'historico operacional', 'histórico operacional')):
        return _format_history(recovery_history(20) or memory_recent(20, kind='action'))
    if t in {'ferramentas', 'tools', 'listar ferramentas'} or 'quais ferramentas' in t:
        return pretty(list_tools())
    if t.startswith('reinicie ') or t.startswith('reiniciar '):
        for alias, service in SERVICE_ALIASES.items():
            if alias in t:
                return pretty(call_tool('system.restart_service', {'service': service}))
    return None


def ask(text: str) -> str:
    direct = _safe_direct_action(text)
    if direct is not None:
        return direct
    plan = classify_plan(text)
    if plan:
        return diagnose_with_plan(text, plan)
    r = route(text)
    if r == 'health':
        return format_health(local_status())
    if r == 'projects':
        return _format_projects()
    if r == 'incidents':
        return _format_incidents()
    if r in {'services', 'docker', 'cron_status', 'cron_list', 'gateway_logs', 'llm_logs', 'router_logs'}:
        return pretty(run_tool(r))
    return llm(text)


def main() -> int:
    if len(sys.argv) > 1:
        print(ask(' '.join(sys.argv[1:])), flush=True)
        return 0
    print('Hermes Core v2.2 - local-first autonomous', flush=True)
    while True:
        try:
            text = input('\nVoce > ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if text.lower() in {'sair', 'exit', 'quit'}:
            return 0
        if text:
            try:
                print('\nHermes > ' + ask(text), flush=True)
            except Exception as e:
                print(f'\nHermes > erro: {e}', flush=True)


if __name__ == '__main__':
    raise SystemExit(main())