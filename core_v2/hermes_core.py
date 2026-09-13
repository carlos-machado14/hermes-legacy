#!/usr/bin/env python3
from __future__ import annotations
import json, os, subprocess, sys, time
from pathlib import Path
import httpx, psutil, yaml
from tools import run_tool, pretty
from planner import classify as classify_plan, execute as execute_plan, compact_for_llm

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


def llm(prompt: str, system: str | None = None) -> str:
    system = system or ('Voce e Hermes Core, um agente local-first rodando na VPS. '
                        'Seja objetivo, nao invente resultados de ferramentas e priorize acoes deterministicas.')
    payload = {
        'model': MODEL,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0.2,
        'max_tokens': MAX_TOKENS,
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
    service_ok = all(services.get(k) == 'active' for k in ('llm', 'gateway', 'router'))
    overall = 'OK' if service_ok and data.get('llm_ready') else 'ATENCAO'
    return (
        f'Hermes VPS: {overall}\n'
        f"CPU: {data['cpu_percent']}% | RAM: {data['ram_percent']}% ({data['ram_available_mb']} MB livres) | "
        f"Swap: {data['swap_percent']}% | Disco: {data['disk_percent']}%\n"
        f"Load: {data['load']} | Uptime: {data['uptime_hours']}h\n"
        f"LLM: {services.get('llm')} | Gateway: {services.get('gateway')} | Router: {services.get('router')} | "
        f"Health: {services.get('health_monitor')}\n"
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
    if 'logs do gateway' in t or 'log do gateway' in t:
        return 'gateway_logs'
    if 'logs do llm' in t or 'log do llm' in t or 'logs do modelo' in t:
        return 'llm_logs'
    if 'logs do router' in t or 'log do router' in t:
        return 'router_logs'
    return 'llm'


def diagnose_with_plan(text: str, plan_name: str) -> str:
    report = execute_plan(plan_name)
    evidence = compact_for_llm(report)
    prompt = (
        'Analise somente as evidencias reais abaixo. Responda em portugues com: '
        '1) causa mais provavel, 2) evidencias, 3) proxima acao segura. '
        'Nao invente dados e seja curto.\n\n'
        f'Pedido: {text}\n\nEvidencias:\n{evidence}'
    )
    try:
        return llm(prompt)
    except Exception:
        return 'Diagnostico coletado, mas o LLM nao respondeu. Evidencias:\n' + pretty(report)


def ask(text: str) -> str:
    plan = classify_plan(text)
    if plan:
        return diagnose_with_plan(text, plan)
    r = route(text)
    if r == 'health':
        return format_health(local_status())
    if r in {'services', 'docker', 'cron_status', 'cron_list', 'gateway_logs', 'llm_logs', 'router_logs'}:
        return pretty(run_tool(r))
    return llm(text)


def main() -> int:
    if len(sys.argv) > 1:
        print(ask(' '.join(sys.argv[1:])), flush=True)
        return 0
    print('Hermes Core v2 - local-first', flush=True)
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
