from __future__ import annotations

import os
import time
from typing import Any

import psutil

MAX_CPU = float(os.getenv('HERMES_MAX_CPU_PERCENT', '88'))
MAX_MEMORY = float(os.getenv('HERMES_MAX_MEMORY_PERCENT', '86'))
MIN_AVAILABLE_MB = int(os.getenv('HERMES_MIN_AVAILABLE_MB', '700'))


def snapshot() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    return {
        'cpu_percent': round(psutil.cpu_percent(interval=0.15), 1),
        'memory_percent': round(float(vm.percent), 1),
        'memory_available_mb': int(vm.available / 1024 / 1024),
        'load_1m': round(os.getloadavg()[0], 2) if hasattr(os, 'getloadavg') else 0,
    }


def can_start_heavy() -> tuple[bool, str, dict[str, Any]]:
    s = snapshot()
    if s['cpu_percent'] >= MAX_CPU:
        return False, f"CPU alta ({s['cpu_percent']}%)", s
    if s['memory_percent'] >= MAX_MEMORY:
        return False, f"Memória alta ({s['memory_percent']}%)", s
    if s['memory_available_mb'] < MIN_AVAILABLE_MB:
        return False, f"Memória livre baixa ({s['memory_available_mb']} MB)", s
    return True, 'ok', s


def wait_until_available(timeout: int = 90, interval: int = 5) -> tuple[bool, str, dict[str, Any]]:
    end = time.time() + max(0, timeout)
    last = snapshot()
    reason = 'ok'
    while True:
        ok, reason, last = can_start_heavy()
        if ok:
            return True, reason, last
        if time.time() >= end:
            return False, reason, last
        time.sleep(max(1, interval))
