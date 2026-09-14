from __future__ import annotations

import json
import re
import time
from typing import Any

import hermes_core
from agent_orchestrator import context_for_step
from audit_log import record as audit_record
from execution_planner import build_plan
from job_store import checkpoint, get_job, list_jobs, update_job
from resource_manager import wait_until_available
from result_validator import validate_final, validate_step
from site_auditor import audit, format_audit
from site_crawler import crawl
from web_research import format_research, research, research_company

MAX_ATTEMPTS_PER_STEP = 3
URL_RE = re.compile(r'https?://[^\s)>\]]+', re.I)
HEAVY_TOOLS = {'llm','web_research','site_audit','site_crawl'}


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
        return '\n\n'.join(json.dumps(report, ensure_ascii=False)[:12000] for report in reports)
    return None


def _execute_step(job: dict[str, Any], step: dict[str, Any], previous: list[str]) -> str:
    tool_output = _execute_tool(job, step, previous)
    if tool_output is not None:
        return tool_output
    context = '\n\n'.join(previous[-3:])[-6000:]
    specialist = context_for_step(step, str(job.get('request') or ''))
    prompt = (
        f"{specialist}\n\n"
        f"MISSÃO ORIGINAL\n{job['request']}\n\n"
        f"ETAPA ATUAL\n{step.get('title')}\n{step.get('instruction')}\n\n"
        f"RESULTADOS ANTERIORES\n{context or 'Nenhum.'}\n\n"
        "Execute somente esta etapa. Use os dados reais coletados nas etapas anteriores. "
        "Não afirme que uma ação externa ocorreu sem evidência real. Entregue resultado objetivo e completo."
    )
    return hermes_core.ask(prompt)


def _should_stop(job_id: str) -> tuple[bool, dict[str, Any] | None]:
    current = get_job(job_id)
    if not current:
        return True, None
    return current.get('status') in {'paused','cancelled'}, current


def run_job(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise KeyError(job_id)
    if job['status'] in {'done','cancelled','paused'}:
        return job

    audit_record('job.run.started', job_id=job_id, request=job.get('request','')[:500])
    if not job.get('plan'):
        update_job(job_id, status='planning', error='')
        plan = build_plan(job['request'])
        job = update_job(job_id, plan=plan, status='queued', current_step=0)
        audit_record('job.planned', job_id=job_id, steps=len(plan))

    plan = list(job.get('plan') or [])
    previous_outputs: list[str] = []
    from job_store import checkpoints
    for item in checkpoints(job_id):
        if item.get('status') == 'done' and item.get('output'):
            previous_outputs.append(str(item['output']))

    start = int(job.get('current_step') or 0)
    for index in range(start, len(plan)):
        stop, current = _should_stop(job_id)
        if stop:
            audit_record('job.run.stopped', job_id=job_id, status=(current or {}).get('status','missing'))
            return current or {}
        step = plan[index]
        title = str(step.get('title') or f'Etapa {index+1}')
        tool = str(step.get('tool') or 'llm')
        if tool in HEAVY_TOOLS:
            ok, reason, resources = wait_until_available(timeout=90)
            if not ok:
                checkpoint(job_id, index, title, 'resource_wait', json.dumps(resources, ensure_ascii=False))
                audit_record('job.resource.wait_timeout', job_id=job_id, step=index, reason=reason, resources=resources)
                return update_job(job_id, status='queued', error=f'Aguardando recursos: {reason}')

        update_job(job_id, status='running', current_step=index, error='')
        checkpoint(job_id, index, title, 'started', '')
        audit_record('job.step.started', job_id=job_id, step=index, title=title, domain=step.get('domain'), tool=tool)

        success = False
        last_output = ''
        reason = ''
        for attempt in range(1, MAX_ATTEMPTS_PER_STEP + 1):
            stop, current = _should_stop(job_id)
            if stop:
                return current or {}
            update_job(job_id, attempts=int((get_job(job_id) or {}).get('attempts') or 0) + 1)
            try:
                last_output = _execute_step(get_job(job_id) or job, step, previous_outputs)
                success, reason = validate_step(step, last_output)
            except Exception as exc:
                last_output = f'Falha da etapa: {exc}'
                success, reason = False, str(exc)
            checkpoint(job_id, index, title, 'done' if success else f'retry_{attempt}', last_output)
            audit_record('job.step.attempt', job_id=job_id, step=index, attempt=attempt, success=success, reason=reason[:500])
            if success:
                break
            time.sleep(min(2 ** attempt, 8))

        if not success:
            audit_record('job.needs_attention', job_id=job_id, step=index, reason=reason[:1000])
            return update_job(job_id, status='needs_attention', error=f'{title}: {reason}', result='\n\n'.join(previous_outputs)[-16000:])

        previous_outputs.append(last_output)
        update_job(job_id, current_step=index + 1)

    update_job(job_id, status='validating')
    ok, reason = validate_final(job['request'], previous_outputs)
    if not ok:
        audit_record('job.validation.failed', job_id=job_id, reason=reason[:1000])
        return update_job(job_id, status='needs_attention', error=reason, result='\n\n'.join(previous_outputs)[-24000:])

    final = '\n\n'.join(previous_outputs).strip()
    audit_record('job.done', job_id=job_id, steps=len(plan), result_chars=len(final))
    return update_job(job_id, status='done', current_step=len(plan), result=final[-30000:], error='')


def run_pending_once(limit: int = 2) -> list[dict[str, Any]]:
    jobs = list_jobs('queued', limit)
    results = []
    for job in jobs:
        try:
            results.append(run_job(str(job['id'])))
        except Exception as exc:
            audit_record('job.crashed', job_id=str(job.get('id')), error=str(exc)[:1000])
            results.append(update_job(str(job['id']), status='needs_attention', error=str(exc)))
    return results
