#!/usr/bin/env python3
from __future__ import annotations
import json, os, subprocess, sys, time
from pathlib import Path
import httpx, psutil, yaml

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
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(f'{BASE_URL}/chat/completions', json=payload)
        r.raise_for_status()
        return r.json()['choices'][0]['message']['content'].strip()


def system_health() -> dict:
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage('/')
    return {
        'cpu_percent': psutil.cpu_percent(interval=0.4),
        'ram_percent': vm.percent,
        'ram_available_mb': round(vm.available / 1024 / 1024),
        'swap_percent': swap.percent,
        'disk_percent': disk.percent,
        'load': list(os.getloadavg()),
        'uptime_hours': round((time.time() - psutil.boot_time()) / 3600, 1),
    }


def service_state(name: str) -> str:
    p = subprocess.run(['systemctl', '--user', 'is-active', name], text=True, capture_output=True, timeout=8)
    return (p.stdout or p.stderr).strip() or 'unknown'


def local_status() -> dict:
    data = system_health()
    data['services'] = {
        'llm': service_state('hermes-local-llm.service'),
        'gateway': service_state('hermes-gateway.service'),
        'router': service_state('hermes-fast-router.service'),
    }
    try:
        with httpx.Client(timeout=5) as client:
            r = client.get(f'{BASE_URL}/models')
            data['llm_http'] = r.status_code
            data['llm_ready'] = r.status_code == 200
    except Exception as e:
        data['llm_http'] = None
        data['llm_ready'] = False
        data['llm_error'] = str(e)
    return data


def route(text: str) -> str:
    t = text.lower().strip()
    if any(k in t for k in ('status da vps', 'saude da vps', 'saúde da vps', 'verifique a vps', 'como esta a vps', 'como está a vps')):
        return 'health'
    if t in {'status', 'health', '/health'}:
        return 'health'
    return 'llm'


def ask(text: str) -> str:
    r = route(text)
    if r == 'health':
        data = local_status()
        return llm('Resuma em portugues, em poucas linhas, este status real da VPS. Nao invente nada:\n' + json.dumps(data, ensure_ascii=False))
    return llm(text)


def main() -> int:
    if len(sys.argv) > 1:
        print(ask(' '.join(sys.argv[1:])))
        return 0
    print('Hermes Core v2 - local-first')
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
                print('\nHermes > ' + ask(text))
            except Exception as e:
                print(f'\nHermes > erro: {e}')


if __name__ == '__main__':
    raise SystemExit(main())
