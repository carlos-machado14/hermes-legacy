#!/usr/bin/env python3
from __future__ import annotations

import signal
import time

from execution_runtime import run_pending_once
from job_store import recover_interrupted

RUNNING = True


def _stop(*_args) -> None:
    global RUNNING
    RUNNING = False


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    recovered = recover_interrupted()
    print(f'Hermes Durable Worker iniciado; jobs recuperados={recovered}', flush=True)
    while RUNNING:
        try:
            results = run_pending_once(limit=1)
            if results:
                for item in results:
                    print(f"job={item.get('id')} status={item.get('status')}", flush=True)
                time.sleep(1)
            else:
                time.sleep(3)
        except Exception as exc:
            print(f'durable worker error: {exc}', flush=True)
            time.sleep(5)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
