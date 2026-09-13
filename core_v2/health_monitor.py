#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, time
from pathlib import Path
from event_bus import publish
from memory_store import remember
from recovery_engine import recover_once

SERVICES = [
    'hermes-local-llm.service',
    'hermes-gateway.service',
    'hermes-fast-router.service',
]
STATE = Path.home() / '.hermes/core-v2/state/health.json'
LOG = Path.home() / '.hermes/core-v2/logs/health.log'
INTERVAL = 60
FAILURES_BEFORE_RECOVERY = 2


def run(args: list[str], timeout: int = 10) -> tuple[int, str]:
    p = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    return p.returncode, ((p.stdout or '') + (p.stderr or '')).strip()


def active(service: str) -> bool:
    code, out = run(['systemctl', '--user', 'is-active', service], 5)
    return code == 0 and out.strip() == 'active'


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f'{time.strftime("%Y-%m-%d %H:%M:%S")} {msg}\n'
    with LOG.open('a', encoding='utf-8') as f:
        f.write(line)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except Exception:
        return {'failures': {}}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')


def once() -> dict:
    state = load_state()
    failures = state.setdefault('failures', {})
    report = {}
    needs_recovery = False
    for service in SERVICES:
        if active(service):
            failures[service] = 0
            report[service] = 'active'
            continue
        failures[service] = int(failures.get(service, 0)) + 1
        report[service] = f'inactive:{failures[service]}'
        publish('service.inactive', {'service': service, 'failures': failures[service]}, source='health')
        if failures[service] >= FAILURES_BEFORE_RECOVERY:
            needs_recovery = True
    if needs_recovery:
        recovery = recover_once()
        report['recovery'] = recovery
        log(f'recovery={json.dumps(recovery, ensure_ascii=False)}')
        remember('health', 'health monitor acionou recovery engine', recovery, recovery.get('ok'))
        for service in SERVICES:
            if active(service):
                failures[service] = 0
                if report.get(service, '').startswith('inactive'):
                    report[service] = 'recovered'
                    publish('service.recovered', {'service': service}, source='health')
    state['last_check'] = int(time.time())
    state['last_report'] = report
    save_state(state)
    return report


def main() -> int:
    log('health-monitor started')
    remember('health', 'health monitor started', {'interval': INTERVAL}, True)
    while True:
        try:
            once()
        except Exception as e:
            log(f'error={e!r}')
            remember('health', 'health monitor error', {'error': repr(e)}, False)
        time.sleep(INTERVAL)


if __name__ == '__main__':
    raise SystemExit(main())
