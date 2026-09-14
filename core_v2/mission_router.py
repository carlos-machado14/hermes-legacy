from __future__ import annotations

import re

from job_store import create_job, get_job, list_jobs, recover_interrupted, update_job


def _fmt(job: dict) -> str:
    jid = job.get('id','?')
    status = job.get('status','?')
    title = job.get('title','')
    step = int(job.get('current_step') or 0)
    total = len(job.get('plan') or [])
    extra = f' etapa {step}/{total}' if total else ''
    return f'[{jid}] {status}{extra} — {title}'


def handle(text: str) -> str | None:
    raw = text.strip()
    low = raw.casefold()

    if low in {'meus jobs','meus trabalhos','tarefas em andamento','missões em andamento','missoes em andamento','status das missões','status das missoes'}:
        jobs = list_jobs(None, 20)
        if not jobs:
            return 'Nenhuma missão durável registrada.'
        return 'Missões Hermes:\n' + '\n'.join(f'- {_fmt(j)}' for j in jobs)

    m = re.search(r'\b(?:status|ver)\s+(?:do\s+)?(?:job|miss[aã]o)\s+([0-9a-f]{6,16})\b', low)
    if m:
        job = get_job(m.group(1))
        if not job:
            return 'Não encontrei essa missão.'
        parts = [_fmt(job)]
        if job.get('error'):
            parts.append(f"Atenção: {job['error']}")
        if job.get('result') and job.get('status') == 'done':
            parts.append('Resultado:\n' + str(job['result'])[-6000:])
        return '\n\n'.join(parts)

    if low in {'retomar jobs','retomar missões','retomar missoes','continue todas as missões','continue todas as missoes'}:
        count = recover_interrupted()
        for job in list_jobs('needs_attention', 50):
            update_job(str(job['id']), status='queued', error='')
            count += 1
        return f'Retomei {count} missão(ões). O executor continuará sozinho até concluir ou encontrar um bloqueio real.'

    prefixes = (
        'missão:', 'missao:', 'execute até finalizar ', 'execute ate finalizar ',
        'trabalhe até concluir ', 'trabalhe ate concluir ', 'faça até finalizar ', 'faca ate finalizar ',
    )
    request = None
    for prefix in prefixes:
        if low.startswith(prefix):
            request = raw[len(prefix):].strip()
            break
    if request:
        job = create_job(request)
        return (
            f"Missão criada: [{job['id']}]\n"
            f"{job['title']}\n"
            "Vou planejar, executar, salvar checkpoints e retomar automaticamente após reinícios. "
            "Você pode acompanhar com: meus jobs"
        )

    return None
