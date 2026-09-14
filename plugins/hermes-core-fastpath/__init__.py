from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("hermes_core_fastpath")

CRON_RE = re.compile(
    r"(?:\b(?:crie|criar|adicione|adicionar|agende|agendar|pause|pausar|pare|parar|"
    r"retome|retomar|remova|remover|apague|apagar|rode|rodar|execute|executar|atualize|atualizar|melhore|melhorar|ajuste|ajustar)\b.*"
    r"\b(?:rotina|rotinas|cron|crons|lembrete|brief|briefing|todo dia|todos os dias|diariamente|a cada|not[ií]cias?)\b|"
    r"\b(?:me lembre|lembre-me)\b|"
    r"\b(?:todo dia|todos os dias|diariamente|a cada\s+\d+\s+(?:minutos?|horas?|dias?))\b.*"
    r"\b(?:mande|envie|avise|lembre|not[ií]cias?)\b|"
    r"\b(?:quais rotinas|minhas rotinas|listar rotinas|liste as rotinas|listar crons)\b)",
    re.IGNORECASE,
)

CONTINUE_RE = re.compile(
    r"^(?:sim[,.! ]*)?(?:continue|continua|continuar|pode continuar|pode seguir|siga|segue|prossiga)[.! ]*$",
    re.IGNORECASE,
)

CANCEL_RE = re.compile(
    r"^(?:pare|para|cancele|cancelar|cancela|interrompa|interromper|"
    r"esquece isso|esqueça isso|deixa pra l[aá]|deixe pra l[aá]|para isso|pare isso)[.! ]*$",
    re.IGNORECASE,
)

REPLACE_RE = re.compile(
    r"^(?:esquece isso|esqueça isso|cancela isso|cancele isso|deixa isso|deixe isso)"
    r"(?:\s+e\s+|\s*,\s*)(.+)$",
    re.IGNORECASE | re.DOTALL,
)

_HARD_HINTS = (
    'analise profundamente', 'análise profunda', 'detalhadamente', 'passo a passo',
    'arquitetura', 'refatore', 'refatorar', 'investigue', 'diagnostique',
    'pesquisa completa', 'pesquise profundamente', 'causa raiz', 'root cause',
    'revise o projeto', 'implemente completo', 'implemente completa',
)

_MISSION_HINTS = (
    'missão:', 'missao:', 'execute até finalizar', 'execute ate finalizar',
    'trabalhe até concluir', 'trabalhe ate concluir', 'faça até finalizar',
    'faca ate finalizar',
)

_TIMEOUTS = {
    'fast': 15,
    'normal': 45,
    'hard': 120,
    'mission': 300,
    'cron': 120,
}


@dataclass
class Job:
    gateway: Any
    source: Any
    text: str
    is_cron: bool
    loop: asyncio.AbstractEventLoop
    trace_id: str
    tier: str
    generation: int
    enqueued_at: float


_JOB_QUEUE: queue.Queue[Job] = queue.Queue(maxsize=100)
_WORKER_STARTED = False
_WORKER_LOCK = threading.Lock()
_ACTIVE_CHATS: set[str] = set()
_ACTIVE_LOCK = threading.Lock()
_ACTIVE_PROCS: dict[str, subprocess.Popen[str]] = {}
_PROC_LOCK = threading.Lock()
_CHAT_GENERATION: dict[str, int] = {}
_GENERATION_LOCK = threading.Lock()


def _trace_id() -> str:
    return uuid.uuid4().hex[:12]


def _chat_key(source: Any) -> str:
    platform = str(getattr(getattr(source, 'platform', None), 'value', '') or '').strip().lower()
    chat_id = str(getattr(source, 'chat_id', '') or '').strip()
    return f"{platform}:{chat_id}" if chat_id else ''


def _set_active(source: Any, active: bool) -> None:
    key = _chat_key(source)
    if not key:
        return
    with _ACTIVE_LOCK:
        if active:
            _ACTIVE_CHATS.add(key)
        else:
            _ACTIVE_CHATS.discard(key)


def _is_active(source: Any) -> bool:
    key = _chat_key(source)
    if not key:
        return False
    with _ACTIVE_LOCK:
        return key in _ACTIVE_CHATS


def _generation(key: str) -> int:
    with _GENERATION_LOCK:
        return int(_CHAT_GENERATION.get(key, 0))


def _invalidate_chat(key: str) -> int:
    with _GENERATION_LOCK:
        value = int(_CHAT_GENERATION.get(key, 0)) + 1
        _CHAT_GENERATION[key] = value
        return value


def _is_stale(key: str, generation: int) -> bool:
    return _generation(key) != generation


def _classify_complexity(text: str, is_cron: bool = False) -> str:
    if is_cron:
        return 'cron'
    low = str(text or '').casefold().strip()
    if not low:
        return 'fast'
    if re.match(r'^\s*(?:responda|responde)\s+(?:apenas|somente)\s*:', low):
        return 'fast'
    if any(low.startswith(h) for h in _MISSION_HINTS):
        return 'mission'
    score = 0
    words = len(re.findall(r'\S+', low))
    if words >= 110 or len(low) >= 750:
        score += 2
    elif words >= 65 or len(low) >= 420:
        score += 1
    score += sum(1 for hint in _HARD_HINTS if hint in low)
    if re.search(r'\b(?:analise|compare|investigue|diagnostique|planeje|implemente|refatore)\b', low):
        score += 1
    return 'hard' if score >= 2 else 'normal'


def _env_value(name: str) -> str:
    value = (os.getenv(name) or '').strip()
    if value:
        return value
    env_file = Path.home() / '.hermes' / '.env'
    try:
        for line in env_file.read_text(encoding='utf-8').splitlines():
            raw = line.strip()
            if not raw or raw.startswith('#') or '=' not in raw:
                continue
            key, val = raw.split('=', 1)
            if key.strip() == name:
                return val.strip().strip('"').strip("'")
    except Exception:
        pass
    return ''


def _allowlist_contains(raw: str, user_id: Any) -> bool:
    uid = str(user_id or '').strip()
    if not uid:
        return False
    allowed = {part.strip() for part in str(raw or '').split(',') if part.strip()}
    return '*' in allowed or uid in allowed


def _authorized(gateway: Any, source: Any) -> bool:
    platform = str(getattr(getattr(source, 'platform', None), 'value', '') or '').strip().lower()
    user_id = getattr(source, 'user_id', None)
    chat_id = getattr(source, 'chat_id', None)

    checker = getattr(gateway, '_is_user_authorized_for_source', None)
    if callable(checker):
        try:
            result = bool(checker(source))
            logger.info("fastpath auth=native result=%s platform=%s chat=%s user=%s", result, platform, chat_id, user_id)
            return result
        except Exception as exc:
            logger.warning("fastpath native auth failed, trying compatibility path: %s", exc)

    stores = []
    store_for = getattr(gateway, '_pairing_store_for', None)
    if callable(store_for):
        try:
            stores.append(store_for(source))
        except Exception:
            pass
    stores.append(getattr(gateway, 'pairing_store', None))
    for store in stores:
        if store is None:
            continue
        approved = getattr(store, 'is_approved', None)
        if callable(approved):
            try:
                if bool(approved(platform, str(user_id))):
                    logger.info("fastpath auth=pairing result=True platform=%s chat=%s user=%s", platform, chat_id, user_id)
                    return True
            except Exception as exc:
                logger.debug("fastpath pairing auth check failed: %s", exc)

    env_name = {
        'telegram': 'TELEGRAM_ALLOWED_USERS',
        'discord': 'DISCORD_ALLOWED_USERS',
        'whatsapp': 'WHATSAPP_ALLOWED_USERS',
        'whatsapp_cloud': 'WHATSAPP_CLOUD_ALLOWED_USERS',
        'slack': 'SLACK_ALLOWED_USERS',
        'signal': 'SIGNAL_ALLOWED_USERS',
    }.get(platform)
    if env_name and _allowlist_contains(_env_value(env_name), user_id):
        logger.info("fastpath auth=platform_allowlist result=True platform=%s chat=%s user=%s", platform, chat_id, user_id)
        return True
    if _allowlist_contains(_env_value('GATEWAY_ALLOWED_USERS'), user_id):
        logger.info("fastpath auth=global_allowlist result=True platform=%s chat=%s user=%s", platform, chat_id, user_id)
        return True

    allow_all_name = f"{platform.upper()}_ALLOW_ALL_USERS" if platform else ''
    if allow_all_name and _env_value(allow_all_name).lower() in {'1', 'true', 'yes'}:
        logger.warning("fastpath auth=explicit_allow_all result=True platform=%s chat=%s user=%s", platform, chat_id, user_id)
        return True
    if _env_value('GATEWAY_ALLOW_ALL_USERS').lower() in {'1', 'true', 'yes'}:
        logger.warning("fastpath auth=explicit_global_allow_all result=True platform=%s chat=%s user=%s", platform, chat_id, user_id)
        return True

    logger.warning("fastpath auth=compat result=False platform=%s chat=%s user=%s", platform, chat_id, user_id)
    return False


def _remember_channel(source: Any) -> None:
    platform = str(getattr(getattr(source, 'platform', None), 'value', '') or '').strip().lower()
    chat_id = str(getattr(source, 'chat_id', '') or '').strip()
    user_id = str(getattr(source, 'user_id', '') or '').strip()
    if platform != 'telegram' or not chat_id:
        return
    try:
        path = Path.home() / '.hermes' / 'core-v2' / 'state' / 'channel_state.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {'platform': platform, 'chat_id': chat_id, 'user_id': user_id, 'updated_at': int(time.time())}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as exc:
        logger.warning("fastpath could not remember proactive channel: %s", exc)


def _register_proc(key: str, proc: subprocess.Popen[str] | None) -> None:
    if not key:
        return
    with _PROC_LOCK:
        if proc is None:
            _ACTIVE_PROCS.pop(key, None)
        else:
            _ACTIVE_PROCS[key] = proc


def _cancel_chat(source: Any, trace: str) -> bool:
    key = _chat_key(source)
    if not key:
        return False
    _invalidate_chat(key)
    proc: subprocess.Popen[str] | None = None
    with _PROC_LOCK:
        proc = _ACTIVE_PROCS.get(key)
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            logger.info("fastpath trace=%s cancel terminate chat=%s pid=%s", trace, key, proc.pid)
            return True
        except Exception as exc:
            logger.warning("fastpath trace=%s cancel failed chat=%s error=%s", trace, key, exc)
    logger.info("fastpath trace=%s cancel invalidated queued work chat=%s", trace, key)
    return False


def _run_process(
    args: list[str],
    *,
    cwd: str,
    timeout: int,
    key: str,
    trace: str,
    tier: str,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env['HERMES_TRACE_ID'] = trace
    if tier != 'cron':
        env['HERMES_COMPLEXITY'] = tier

    proc = subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _register_proc(key, proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=2)
        except Exception:
            proc.kill()
            stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(args, timeout, output=stdout, stderr=stderr)
    finally:
        _register_proc(key, None)
    return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)


def _run_core(text: str, *, key: str, trace: str, tier: str) -> str:
    root = Path.home() / '.hermes' / 'core-v2'
    py = root / 'venv' / 'bin' / 'python'
    core = root / 'core_entry.py'
    timeout = int(_TIMEOUTS.get(tier, 45))
    started = time.perf_counter()
    proc = _run_process(
        [str(py), str(core), text],
        cwd=str(root),
        timeout=timeout,
        key=key,
        trace=trace,
        tier=tier,
    )
    elapsed = (time.perf_counter() - started) * 1000
    logger.info(
        "fastpath trace=%s stage=core tier=%s elapsed_ms=%.2f rc=%s stdout_len=%s stderr_len=%s",
        trace, tier, elapsed, proc.returncode, len(proc.stdout or ''), len(proc.stderr or ''),
    )
    if proc.returncode != 0:
        return f"⚠️ Não consegui concluir essa resposta. Detalhe: {(proc.stderr or proc.stdout)[-500:].strip()}"
    return (proc.stdout or '').strip() or 'Não encontrei uma resposta confiável para isso ainda.'


def _run_cron(text: str, *, key: str, trace: str) -> str:
    root = Path.home() / '.hermes' / 'core-v2'
    py = root / 'venv' / 'bin' / 'python'
    manager = root / 'cron_manager.py'
    encoded = base64.urlsafe_b64encode(text.encode('utf-8')).decode('ascii')
    started = time.perf_counter()
    proc = _run_process(
        [str(py), str(manager), '--text-b64', encoded],
        cwd=str(root),
        timeout=_TIMEOUTS['cron'],
        key=key,
        trace=trace,
        tier='cron',
    )
    raw = (proc.stdout or '').strip()
    logger.info(
        "fastpath trace=%s stage=cron elapsed_ms=%.2f rc=%s stdout_len=%s stderr_len=%s",
        trace, (time.perf_counter() - started) * 1000, proc.returncode, len(raw), len(proc.stderr or ''),
    )
    if proc.returncode != 0:
        return f"⚠️ Não consegui concluir essa rotina agora. Detalhe: {(proc.stderr or raw)[-500:].strip()}"
    marker = 'HERMES_CRON_RESULT:'
    if marker in raw:
        return raw.rsplit(marker, 1)[-1].strip()
    return raw or 'Rotina processada.'


def _split_message(text: str, limit: int = 3600) -> list[str]:
    text = (text or '').strip()
    if not text:
        return ['Não encontrei uma resposta confiável para isso ainda.']
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining.strip())
            break
        cut = remaining.rfind('\n\n', 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind('\n', 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(' ', 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].lstrip()

    if len(chunks) <= 1:
        return chunks
    total = len(chunks)
    return [f"[{i}/{total}]\n{chunk}" for i, chunk in enumerate(chunks, 1)]


async def _send_all(adapter: Any, chat_id: Any, chunks: list[str], trace: str) -> None:
    started = time.perf_counter()
    for index, chunk in enumerate(chunks, 1):
        await adapter.send(chat_id, chunk)
        logger.info(
            "fastpath trace=%s stage=send_chunk chat=%s part=%s/%s chars=%s",
            trace, chat_id, index, len(chunks), len(chunk),
        )
        if index < len(chunks):
            await asyncio.sleep(0.15)
    logger.info(
        "fastpath trace=%s stage=send_total chat=%s elapsed_ms=%.2f chunks=%s",
        trace, chat_id, (time.perf_counter() - started) * 1000, len(chunks),
    )


def _schedule_send(
    loop: asyncio.AbstractEventLoop,
    gateway: Any,
    source: Any,
    text: str,
    trace: str,
) -> None:
    if loop.is_closed():
        logger.error("fastpath trace=%s send skipped: gateway event loop is closed", trace)
        return

    chunks = _split_message(text)

    def submit() -> None:
        try:
            adapter = gateway._adapter_for_source(source)
            if adapter is None:
                logger.error("fastpath trace=%s send failed: adapter ausente", trace)
                return
            task = loop.create_task(_send_all(adapter, source.chat_id, chunks, trace))

            def done_callback(done: asyncio.Task) -> None:
                try:
                    done.result()
                except Exception as exc:
                    logger.exception("fastpath trace=%s send task failed: %s", trace, exc)

            task.add_done_callback(done_callback)
            logger.info(
                "fastpath trace=%s reply scheduled on gateway_loop chat=%s chunks=%s chars=%s",
                trace, source.chat_id, len(chunks), len(text),
            )
        except Exception as exc:
            logger.exception("fastpath trace=%s send scheduling failed: %s", trace, exc)

    loop.call_soon_threadsafe(submit)


def _process_job(job: Job) -> None:
    key = _chat_key(job.source)
    if _is_stale(key, job.generation):
        logger.info("fastpath trace=%s skipped stale queued job chat=%s", job.trace_id, key)
        return

    queue_ms = (time.perf_counter() - job.enqueued_at) * 1000
    logger.info(
        "fastpath trace=%s stage=dequeue tier=%s queue_ms=%.2f chat=%s",
        job.trace_id, job.tier, queue_ms, key,
    )

    _set_active(job.source, True)
    started = time.perf_counter()
    try:
        reply = (
            _run_cron(job.text, key=key, trace=job.trace_id)
            if job.is_cron
            else _run_core(job.text, key=key, trace=job.trace_id, tier=job.tier)
        )
    except subprocess.TimeoutExpired:
        logger.exception("fastpath trace=%s local execution timeout tier=%s", job.trace_id, job.tier)
        reply = 'Essa solicitação excedeu o limite de tempo desta rota. Tente simplificar ou transforme em uma missão longa.'
    except Exception as exc:
        logger.exception("fastpath trace=%s local execution failed: %s", job.trace_id, exc)
        reply = f'Não consegui concluir essa solicitação agora. Detalhe: {exc}'
    finally:
        _set_active(job.source, False)

    if _is_stale(key, job.generation):
        logger.info("fastpath trace=%s suppressing stale/cancelled reply chat=%s", job.trace_id, key)
        return

    total_ms = (time.perf_counter() - job.enqueued_at) * 1000
    logger.info(
        "fastpath trace=%s stage=ready total_ms=%.2f exec_ms=%.2f tier=%s reply_chars=%s",
        job.trace_id, total_ms, (time.perf_counter() - started) * 1000, job.tier, len(reply),
    )
    _schedule_send(job.loop, job.gateway, job.source, reply, job.trace_id)


def _worker() -> None:
    logger.warning("HERMES CORE FASTPATH background worker started")
    while True:
        job = _JOB_QUEUE.get()
        try:
            _process_job(job)
        except Exception:
            logger.exception("fastpath background job crashed")
        finally:
            _JOB_QUEUE.task_done()


def _ensure_worker() -> None:
    global _WORKER_STARTED
    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return
        threading.Thread(target=_worker, name='hermes-core-fastpath-worker', daemon=True).start()
        _WORKER_STARTED = True


def pre_gateway_dispatch(event: Any = None, **kwargs):
    """Encaminha mensagens normais ao Core sem bloquear o event loop do Gateway."""
    if event is None:
        event = kwargs.get('event')
    gateway = kwargs.get('gateway')
    if event is None or gateway is None:
        logger.warning("fastpath hook invoked without event/gateway")
        return None

    source = getattr(event, 'source', None)
    text = str(getattr(event, 'text', '') or '').strip()
    trace = _trace_id()
    logger.info(
        "fastpath trace=%s stage=inbound text=%r platform=%s chat=%s",
        trace,
        text[:180],
        getattr(getattr(source, 'platform', None), 'value', None) if source else None,
        getattr(source, 'chat_id', None) if source else None,
    )

    if not text or source is None:
        return None
    if not _authorized(gateway, source):
        logger.info("fastpath trace=%s allow legacy path: sender not authorized", trace)
        return None

    _remember_channel(source)
    if text.startswith('/'):
        logger.info("fastpath trace=%s allow slash command=%r", trace, text[:80])
        return None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.error("fastpath trace=%s no running gateway loop; falling back to legacy dispatch", trace)
        return None

    replace = REPLACE_RE.match(text)
    if replace:
        _cancel_chat(source, trace)
        text = replace.group(1).strip()
        if not text:
            _schedule_send(loop, gateway, source, 'Cancelei a solicitação anterior.', trace)
            return {'action': 'skip', 'reason': 'cancelled-and-empty-replacement'}

    if CANCEL_RE.match(text):
        had_active = _cancel_chat(source, trace)
        answer = 'Cancelei a solicitação em andamento.' if had_active else 'Limpei as solicitações pendentes desta conversa.'
        _schedule_send(loop, gateway, source, answer, trace)
        return {'action': 'skip', 'reason': 'user-cancelled-active-work'}

    if CONTINUE_RE.match(text) and _is_active(source):
        logger.info("fastpath trace=%s ignored duplicate continue while chat has active job", trace)
        return {'action': 'skip', 'reason': 'active-job-already-continuing'}

    _ensure_worker()
    is_cron = bool(CRON_RE.search(text))
    tier = _classify_complexity(text, is_cron=is_cron)
    key = _chat_key(source)
    generation = _generation(key)
    job = Job(
        gateway=gateway,
        source=source,
        text=text,
        is_cron=is_cron,
        loop=loop,
        trace_id=trace,
        tier=tier,
        generation=generation,
        enqueued_at=time.perf_counter(),
    )
    try:
        _JOB_QUEUE.put_nowait(job)
        logger.info(
            "fastpath trace=%s stage=queued tier=%s chat=%s queue_size=%s",
            trace, tier, getattr(source, 'chat_id', None), _JOB_QUEUE.qsize(),
        )
    except queue.Full:
        _schedule_send(loop, gateway, source, 'Tenho muitas solicitações locais na fila agora. Tente novamente em alguns instantes.', trace)

    return {'action': 'skip', 'reason': 'hermes-core-background-queue'}


def register(ctx):
    ctx.register_hook('pre_gateway_dispatch', pre_gateway_dispatch)
    _ensure_worker()
    logger.warning("HERMES CORE FASTPATH plugin registered hook=pre_gateway_dispatch v1.7 (gateway-loop safe)")
