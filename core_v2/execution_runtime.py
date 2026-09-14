from __future__ import annotations

import json
import re
import time
from typing import Any

import hermes_core
from execution_planner import build_plan
from job_store import checkpoint, get_job, list_jobs, update_job
from result_validator import validate_final, validate_step
from site_auditor import audit, format_audit
from site_crawler import crawl
from web_research import format_research, research, research_company

MAX_ATTEMPTS_PER_STEP = 3
URL_RE = re.compile(r'https?://[^\s)>\]]+', re.I)


def _urls(previous: list[str]) -> list[str]:
    out: list[str] = []
    for text in reversed(previous):
        for url in URL_RE.findall(text or ''):
            clean = url.rstrip('.,;:')
            if clean not in out:
                out.append(clean)
            if len(out) >= 5:
                return out
    return out


def _execute_tool(job: dict[str, Any], step: dict[str, Any], previous: list[str]) -> str | None:
    tool = str(step.get('tool') or 'llm')
    instruction = str(step.get('instruction') or '')
    request = str(job.get('request') or '')
    if tool == 'web_research':
        report = research_company(request, limit=6) if any(k in request.casefold() for k in ('empresa','dentista','clínica','clinica','lead','negócio','negocio')) else research(instruction or request, limit=8)
        return format_research(report)
    if tool == 'site_audit':
        urls = _urls(previous)
        if not urls:
            report = research(request, limit=5)
            urls = [str(x.get('url') or '') for x in report.get('results') or [] if x.get('url')]
        if not urls:
            return 'Nenhum site real encontrado para auditoria.'
        return '\n\n'.join(format_audit(audit(url)) for url in urls[:3])
    if tool == 'site_crawl':
        urls = _urls(previous)
        if not urls:
            return 'Nenhuma URL encontrada nas etapas anteriores para coleta.'
        reports = [crawl(url, max_pages=5) for url in urls[:3]]
        parts = []
        for report in reports:
            parts.append(json.dumps(report, ensure_ascii=False)[:12000])
        return '\n\n'.join(parts)
    return None


def _execute_step(job: dict[str, Any], step: dict[str, Any], previous: list[str]) -> str:
    tool_output = _execute_tool(job, step, previous)
    if tool_output is not None:
        return tool_output
    context = '\n\n'.join(previous[-3:])[-6000:]
    prompt = (
        f"MISSÃO ORIGINAL\n{job['request']}\n\n"
        f"ETAPA ATUAL\n{step.get('title')}\n{step.get('instruction')}\n\n"
        f"RESULTADOS ANTERIORES\n{context or 'Nenhum.'}\n\n"
        "Execute somente esta etapa. Use os dados reais coletados nas etapas anteriores. "
        "Não afirme que uma ação externa ocorreu sem evidência real. Entregue resultado objetivo e completo."
    )
    return hermes_core.ask(prompt)


def run_job(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise KeyError(job_id)
    if job['status'] in {'done','cancelled'}:
        return job

    if not job.get('plan'):
        update_job(job_id, status='planning', error='')
        plan = build_plan(job['request'])
        job = update_job(job_id, plan=plan, status='queued', current_step=0)

    plan = list(job.get('plan') or [])
    previous_outputs: list[str] = []
    from job_store import checkpoints
    for item in checkpoints(job_id):
        if item.get('status') == 'done' and item.get('output'):
            previous_outputs.append(str(item['output']))

    start = int(job.get('current_step') or 0)
    for index in range(start, len(plan)):
        step = plan[index]
        title = str(step.get('title') or f'Etapa {index+1}')
        update_job(job_id, status='running', current_step=index, error='')
        checkpoint(job_id, index, title, 'started', '')

        success = False
        last_output = ''
        reason = ''
        for attempt in range(1, MAX_ATTEMPTS_PER_STEP + 1):
            update_job(job_id, attempts=int((get_job(job_id) or {}).get('attempts') or 0) + 1)
            try:
                last_output = _execute_step(get_job(job_id) or job, step, previous_outputs)
                success, reason = validate_step(step, last_output)
            except Exception as exc:
                last_output = f'Falha da etapa: {exc}'
                success, reason = False, str(exc)
            checkpoint(job_id, index, title, 'done' if success else f'retry_{attempt}', last_output)
            if success:
                break
            time.sleep(min(2 * attempt, 5))

        if not success:
            return update_job(job_id, status='needs_attention', error=f'{title}: {reason}', result='\n\n'.join(previous_outputs)[-16000:])

        previous_outputs.append(last_output)
        update_job(job_id, current_step=index + 1)

    update_job(job_id, status='validating')
    ok, reason = validate_final(job['request'], previous_outputs)
    if not ok:
        return update_job(job_id, status='needs_attention', error=reason, result='\n\n'.join(previous_outputs)[-24000:])

    final = '\n\n'.join(previous_outputs).strip()
    return update_job(job_id, status='done', current_step=len(plan), result=final[-30000:], error='')


def run_pending_once(limit: int = 2) -> list[dict[str, Any]]:
    jobs = list_jobs('queued', limit)
    results = []
    for job in jobs:
        try:
            results.append(run_job(str(job['id'])))
        except Exception as exc:
            results.append(update_job(str(job['id']), status='needs_attention', error=str(exc)))
    return results
