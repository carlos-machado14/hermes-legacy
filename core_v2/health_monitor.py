#!/usr/bin/env python3
from __future__ import annotations
import json
import subprocess
import time
from pathlib import Path

SERVICES = [
    'hermes-local-llm.service',
    'hermes-gateway.service',
    'hermes-fast-router.service',
]
STATE = Path.home() / '.hermes/core-v2/state/health.json'
LOG = Path.home() / '.hermes/core-v2/logs/health.log'
INTERVAL = 60
FAILURES_BEFORE_RESTART = 2


def run(args: list[str], timeout: int = 10) -> tuple[int, str]:
    p = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    return p.returncode, ((p.stdout or '') + (p.stderr or '')).strip()


def active(service: str) -> bool:
    code, out = run(['systemctl', '--user', 'is-active', service], 5)
    return code == 0 and out.strip() == 'active'


def restart(service: str) -> bool:
    code, _ = run(['systemctl', '--user', 'restart', service], 20)
    return code == 0


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f'{time.strftime("%Y-%m-%d %H:%M:%S")} {msg}\n'
    with LOG.open('a') as f:
        f.write(line)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {'failures': {}}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))


def once() -> dict:
    state = load_state()
    failures = state.setdefault('failures', {})
    report = {}
    for service in SERVICES:
        if active(service):
            failures[service] = 0
            report[service] = 'active'
            continue
        failures[service] = int(failures.get(service, 0)) + 1
        report[service] = f'inactive:{failures[service]}'
        if failures[service] >= FAILURES_BEFORE_RESTART:
            ok = restart(service)
            log(f'auto-restart service={service} ok={ok}')
            time.sleep(3)
            if ok and active(service):
                failures[service] = 0
                report[service] = 'recovered'
    state['last_check'] = int(time.time())
    save_state(state)
    return report


def main() -> int:
    log('health-monitor started')
    while True:
        try:
            once()
        except Exception as e:
            log(f'error={e!r}')
        time.sleep(INTERVAL)


if __name__ == '__main__':
    raise SystemExit(main())
