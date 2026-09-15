#!/usr/bin/env python3
from __future__ import annotations

import os
import signal
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from delivery import send_telegram
from execution_runtime import run_job
from job_store import claim_jobs, list_unnotified, mark_notified, recover_interrupted

RUNNING = True
MAX_WORKERS = max(1, min(8, int(os.getenv('HERMES_FLOW_WORKERS', '4'))))


def _stop(*_args: Any) -> None:
    global RUNNING
    RUNNING = False


def _notify(job: dict[str, Any]) -> bool:
    chat_id = str(job.get('source_chat_id') or '').strip()
    if not chat_id:
        mark_notified(str(job['id']))
        return True
    if job.get('status') == 'done':
        text = f"✅ Finalizei o fluxo {job['id']} — {job.get('title')}\n\n{job.get('result') or 'Concluído.'}"
    else:
        text = (
            f"⚠️ O fluxo {job['id']} precisa de atenção — {job.get('title')}\n\n"
            f"{job.get('error') or 'Não consegui validar a conclusão.'}"
        )
    ok, _ = send_telegram(text, chat_id=chat_id, attempts=3)
    if ok:
        mark_notified(str(job['id']))
    return ok


def _drain_notifications() -> None:
    for job in list_unnotified(20):
        _notify(job)


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    recovered = recover_interrupted()
    print(f'Hermes Multi-Flow Worker ativo; workers={MAX_WORKERS}; recuperados={recovered}', flush=True)
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='hermes-flow')
    active: dict[Future, str] = {}
    try:
        while RUNNING:
            done = [future for future in active if future.done()]
            for future in done:
                job_id = active.pop(future)
                try:
                    result = future.result()
                    print(f"flow={job_id} status={result.get('status')}", flush=True)
                    if result.get('status') in {'done', 'needs_attention'}:
                        _notify(result)
                except Exception as exc:
                    print(f'flow={job_id} crashed: {exc}', flush=True)

            free = MAX_WORKERS - len(active)
            if free > 0:
                for job in claim_jobs(free):
                    job_id = str(job.get('id'))
                    active[pool.submit(run_job, job_id)] = job_id

            _drain_notifications()
            time.sleep(1 if active else 3)
    finally:
        pool.shutdown(wait=False, cancel_futures=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
