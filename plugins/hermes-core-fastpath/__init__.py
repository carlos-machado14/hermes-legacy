from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger('hermes_core_fastpath')

TIME_RE = re.compile(
    r"(?:\b(?:crie|criar|adicione|adicionar|agende|agendar|pause|pausar|pare|parar|retome|retomar|"
    r"remova|remover|apague|apagar|rode|rodar|execute|executar|atualize|atualizar|melhore|melhorar|ajuste|ajustar)\b.*"
    r"\b(?:rotina|rotinas|cron|crons|lembrete|lembretes|agenda|evento|compromisso|brief|briefing|todo dia|todos os dias|diariamente|a cada)\b|"
    r"\b(?:me lembre|lembre-me)\b|"
    r"\b(?:todo dia|todos os dias|diariamente|todo ano|a cada\s+\d+\s+(?:minutos?|horas?|dias?))\b.*"
    r"\b(?:mande|envie|avise|lembre|not[ií]cias?)\b|"
    r"\b(?:quais rotinas|minhas rotinas|meus lembretes|listar rotinas|listar crons|agenda de hoje|agenda de amanhã|agenda de amanha)\b)",
    re.I,
)
CRON_RE = TIME_RE
CONTINUE_RE = re.compile(
    r"^(?:sim[,.! ]*)?(?:continue|continua|continuar|pode continuar|pode seguir|siga|segue|prossiga)[.! ]*$",
    re.I,
)
CANCEL_RE = re.compile(
    r"^(?:pare|para|cancele|cancelar|cancela|interrompa|interromper|esquece isso|esqueça isso|"
    r"deixa pra l[aá]|deixe pra l[aá]|para isso|pare isso)[.! ]*$",
    re.I,
)
REPLACE_RE = re.compile(
    r"^(?:esquece isso|esqueça isso|cancela isso|cancele isso|deixa isso|deixe isso)"
    r"(?:\s+e\s+|\s*,\s*)(.+)$",
    re.I | re.S,
)

_HARD_HINTS = (
    'analise profundamente', 'análise profunda', 'detalhadamente', 'passo a passo', 'arquitetura',
    'refatore', 'refatorar', 'investigue', 'diagnostique', 'causa raiz', 'root cause',
    'revise o projeto', 'otimize tudo', 'corrija tudo',
)
_RESEARCH_HINTS = (
    'pesquise', 'pesquisar', 'procure', 'buscar', 'busque', 'encontre', 'encontrar', 'colete', 'coletar',
    'investigue', 'levante', 'mapear', 'audite', 'auditar', 'possível cliente', 'possivel cliente', 'lead',
    'presença digital', 'presenca digital', 'traga os dados', 'trazer os dados', 'dados de 1 empresa',
    'precisa de um site', 'precisando de um site',
)
_MULTI_HINTS = (
    'todos os dados', 'com todos os dados', 'links', 'imagens', 'contatos', 'telefone', 'whatsapp',
    'instagram', 'compare', 'comparar', 'o melhor', 'melhor opção', 'melhor opcao', 'verifique',
    'validar', 'fontes',
)
_IMPLEMENT_HINTS = (
    'implemente', 'implementar', 'desenvolva', 'desenvolver', 'corrija o projeto', 'aplique no projeto',
    'faça tudo', 'faca tudo', 'implemente tudo', 'implementar tudo', 'refatore o projeto',
    'revise todo', 'revise toda',
)
_MISSION_HINTS = (
    'missão:', 'missao:', 'execute até finalizar', 'execute ate finalizar', 'trabalhe até concluir',
    'trabalhe ate concluir', 'faça até finalizar', 'faca ate finalizar',
)
_TIMEOUTS = {'fast': 15, 'normal': 45, 'hard': 120, 'cron': 120, 'mission': 30}


@dataclass
class Work:
    gateway: Any
    source: Any
    text: str
    loop: asyncio.AbstractEventLoop
    trace_id: str
    tier: str
    is_time: bool
    enqueued_at: float


_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(2, min(12, int(os.getenv('HERMES_GATEWAY_WORKERS', '6')))),
    thread_name_prefix='hermes-fastpath',
)
_PENDING = threading.BoundedSemaphore(max(20, int(os.getenv('HERMES_GATEWAY_PENDING', '100'))))
_PROC_LOCK = threading.Lock()
_ACTIVE_PROCS: dict[str, subprocess.Popen[str]] = {}
_CHAT_TRACES: dict[str, list[str]] = {}


def _trace_id() -> str:
    return uuid.uuid4().hex[:12]


def _chat_key(source: Any) -> str:
    platform = str(getattr(getattr(source, 'platform', None), 'value', '') or '').strip().lower()
    chat_id = str(getattr(source, 'chat_id', '') or '').strip()
    return f'{platform}:{chat_id}' if chat_id else ''


def _register_proc(source: Any, trace: str, proc: subprocess.Popen[str] | None) -> None:
    key = _chat_key(source)
    with _PROC_LOCK:
        if proc is None:
            _ACTIVE_PROCS.pop(trace, None)
            if key and key in _CHAT_TRACES:
                _CHAT_TRACES[key] = [x for x in _CHAT_TRACES[key] if x != trace]
                if not _CHAT_TRACES[key]:
                    _CHAT_TRACES.pop(key, None)
            return
        _ACTIVE_PROCS[trace] = proc
        if key:
            traces = _CHAT_TRACES.setdefault(key, [])
            if trace not in traces:
                traces.append(trace)


def _cancel_latest(source: Any, trace: str) -> bool:
    key = _chat_key(source)
    with _PROC_LOCK:
        traces = list(_CHAT_TRACES.get(key, []))
        for active_trace in reversed(traces):
            proc = _ACTIVE_PROCS.get(active_trace)
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    logger.info('fastpath trace=%s cancelled transient=%s chat=%s', trace, active_trace, key)
                    return True
                except Exception:
                    return False
    return False


def _mission_score(raw: str) -> int:
    low = raw.casefold()
    score = 0
    if any(low.startswith(h) for h in _MISSION_HINTS):
        score += 6
    research = sum(1 for h in _RESEARCH_HINTS if h in low)
    multi = sum(1 for h in _MULTI_HINTS if h in low)
    implementation = sum(1 for h in _IMPLEMENT_HINTS if h in low)
    score += min(research, 2) * 2 + min(multi, 3) + min(implementation, 2) * 2
    if research and multi:
        score += 2
    if research and any(x in low for x in ('empresa', 'cliente', 'negócio', 'negocio', 'site', 'cidade', 'colombo')):
        score += 2
    if implementation and any(x in low for x in ('projeto', 'repo', 'repositório', 'repositorio', 'sistema')):
        score += 2
    words = len(re.findall(r'\S+', raw))
    if words >= 80:
        score += 2
    elif words >= 45:
        score += 1
    return score


def _classify_complexity(text: str, is_cron: bool = False) -> str:
    if is_cron:
        return 'cron'
    low = str(text or '').casefold().strip()
    if not low:
        return 'fast'
    if re.match(r'^\s*(?:responda|responde)\s+(?:apenas|somente)\s*:', low):
        return 'fast'
    if _mission_score(text) >= 6:
        return 'mission'
    score = 0
    words = len(re.findall(r'\S+', low))
    if words >= 110 or len(low) >= 750:
        score += 2
    elif words >= 65 or len(low) >= 420:
        score += 1
    score += sum(1 for hint in _HARD_HINTS if hint in low)
    if re.search(r'\b(?:analise|compare|investigue|diagnostique|planeje|refatore)\b', low):
        score += 1
    return 'hard' if score >= 2 else 'normal'


def _env_value(name: str) -> str:
    value = (os.getenv(name) or '').strip()
    if value:
        return value
    path = Path.home() / '.hermes' / '.env'
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
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
    allowed = {x.strip() for x in str(raw or '').split(',') if x.strip()}
    return '*' in allowed or uid in allowed


def _authorized(gateway: Any, source: Any) -> bool:
    platform = str(getattr(getattr(source, 'platform', None), 'value', '') or '').strip().lower()
    user_id = getattr(source, 'user_id', None)
    checker = getattr(gateway, '_is_user_authorized_for_source', None)
    if callable(checker):
        try:
            return bool(checker(source))
        except Exception:
            pass

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
                    return True
            except Exception:
                pass

    env_name = {
        'telegram': 'TELEGRAM_ALLOWED_USERS',
        'discord': 'DISCORD_ALLOWED_USERS',
        'whatsapp': 'WHATSAPP_ALLOWED_USERS',
        'whatsapp_cloud': 'WHATSAPP_CLOUD_ALLOWED_USERS',
        'slack': 'SLACK_ALLOWED_USERS',
        'signal': 'SIGNAL_ALLOWED_USERS',
    }.get(platform)
    if env_name and _allowlist_contains(_env_value(env_name), user_id):
        return True
    if _allowlist_contains(_env_value('GATEWAY_ALLOWED_USERS'), user_id):
        return True
    if platform and _env_value(f'{platform.upper()}_ALLOW_ALL_USERS').lower() in {'1', 'true', 'yes'}:
        return True
    if _env_value('GATEWAY_ALLOW_ALL_USERS').lower() in {'1', 'true', 'yes'}:
        return True
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
        path.write_text(
            json.dumps(
                {'platform': platform, 'chat_id': chat_id, 'user_id': user_id, 'updated_at': int(time.time())},
                ensure_ascii=False,
                indent=2,
            ),
            encoding='utf-8',
        )
    except Exception as exc:
        logger.warning('fastpath channel save failed: %s', exc)


def _run_process(
    args: list[str],
    *,
    cwd: str,
    timeout: int,
    source: Any,
    trace: str,
    tier: str,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env['HERMES_TRACE_ID'] = trace
    env['HERMES_COMPLEXITY'] = tier
    env['HERMES_SOURCE_PLATFORM'] = str(getattr(getattr(source, 'platform', None), 'value', '') or '')
    env['HERMES_SOURCE_CHAT_ID'] = str(getattr(source, 'chat_id', '') or '')
    env['HERMES_SOURCE_USER_ID'] = str(getattr(source, 'user_id', '') or '')
    proc = subprocess.Popen(args, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _register_proc(source, trace, proc)
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
        _register_proc(source, trace, None)
    return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)


def _run_core(work: Work) -> str:
    root = Path.home() / '.hermes' / 'core-v2'
    py = root / 'venv' / 'bin' / 'python'
    core = root / 'core_entry.py'
    proc = _run_process(
        [str(py), str(core), work.text],
        cwd=str(root),
        timeout=_TIMEOUTS.get(work.tier, 45),
        source=work.source,
        trace=work.trace_id,
        tier=work.tier,
    )
    if proc.returncode != 0:
        return f"⚠️ Não consegui concluir essa resposta. {(proc.stderr or proc.stdout)[-500:].strip()}"
    return (proc.stdout or '').strip() or 'Não encontrei uma resposta confiável para isso ainda.'


def _run_time(work: Work) -> str:
    root = Path.home() / '.hermes' / 'core-v2'
    py = root / 'venv' / 'bin' / 'python'
    manager = root / 'cron_manager.py'
    encoded = base64.urlsafe_b64encode(work.text.encode()).decode()
    proc = _run_process(
        [str(py), str(manager), '--text-b64', encoded],
        cwd=str(root),
        timeout=_TIMEOUTS['cron'],
        source=work.source,
        trace=work.trace_id,
        tier='cron',
    )
    raw = (proc.stdout or '').strip()
    marker = 'HERMES_CRON_RESULT:'
    if proc.returncode != 0:
        return f"⚠️ Não consegui concluir essa rotina agora. {(proc.stderr or raw)[-500:].strip()}"
    return raw.rsplit(marker, 1)[-1].strip() if marker in raw else (raw or 'Rotina processada.')


def _run_flow_submit(work: Work) -> str:
    root = Path.home() / '.hermes' / 'core-v2'
    py = root / 'venv' / 'bin' / 'python'
    submit = root / 'flow_submit.py'
    encoded = base64.urlsafe_b64encode(work.text.encode()).decode()
    proc = _run_process(
        [str(py), str(submit), '--text-b64', encoded],
        cwd=str(root),
        timeout=_TIMEOUTS['mission'],
        source=work.source,
        trace=work.trace_id,
        tier='mission',
    )
    if proc.returncode != 0:
        return f"⚠️ Não consegui iniciar o fluxo. {(proc.stderr or proc.stdout)[-500:].strip()}"
    return (proc.stdout or '').strip()


def _split_message(text: str, limit: int = 3600) -> list[str]:
    text = (text or '').strip()
    if not text:
        return ['Não encontrei uma resposta confiável para isso ainda.']
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
    return [f'[{i}/{total}]\n{chunk}' for i, chunk in enumerate(chunks, 1)]


async def _send_all(adapter: Any, chat_id: Any, chunks: list[str], trace: str) -> None:
    for index, chunk in enumerate(chunks, 1):
        await adapter.send(chat_id, chunk)
        logger.info('fastpath trace=%s sent part=%s/%s chars=%s', trace, index, len(chunks), len(chunk))
        if index < len(chunks):
            await asyncio.sleep(0.1)


def _schedule_send(loop: asyncio.AbstractEventLoop, gateway: Any, source: Any, text: str, trace: str) -> None:
    if loop.is_closed():
        return
    chunks = _split_message(text)

    def submit() -> None:
        try:
            adapter = gateway._adapter_for_source(source)
            if adapter is None:
                return
            task = loop.create_task(_send_all(adapter, source.chat_id, chunks, trace))

            def done_callback(done: asyncio.Task) -> None:
                try:
                    done.result()
                except Exception:
                    logger.exception('fastpath send failed trace=%s', trace)

            task.add_done_callback(done_callback)
        except Exception:
            logger.exception('fastpath send scheduling failed trace=%s', trace)

    loop.call_soon_threadsafe(submit)


def _process(work: Work) -> None:
    try:
        if work.is_time:
            reply = _run_time(work)
        elif work.tier == 'mission':
            reply = _run_flow_submit(work)
        else:
            try:
                reply = _run_core(work)
            except subprocess.TimeoutExpired:
                if work.tier == 'hard':
                    reply = _run_flow_submit(work)
                else:
                    reply = 'Não consegui obter uma resposta confiável dentro do limite local.'
        _schedule_send(work.loop, work.gateway, work.source, reply, work.trace_id)
    except Exception as exc:
        logger.exception('fastpath work failed trace=%s: %s', work.trace_id, exc)
        _schedule_send(
            work.loop,
            work.gateway,
            work.source,
            f'Não consegui concluir essa solicitação agora. Detalhe: {exc}',
            work.trace_id,
        )
    finally:
        _PENDING.release()


def pre_gateway_dispatch(event: Any = None, **kwargs):
    if event is None:
        event = kwargs.get('event')
    gateway = kwargs.get('gateway')
    if event is None or gateway is None:
        return None

    source = getattr(event, 'source', None)
    text = str(getattr(event, 'text', '') or '').strip()
    trace = _trace_id()
    if not text or source is None:
        return None
    if not _authorized(gateway, source):
        return None

    _remember_channel(source)
    if text.startswith('/'):
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None

    replace = REPLACE_RE.match(text)
    if replace:
        _cancel_latest(source, trace)
        text = replace.group(1).strip()
    elif CANCEL_RE.match(text):
        cancelled = _cancel_latest(source, trace)
        answer = (
            'Cancelei a resposta que estava sendo processada.'
            if cancelled
            else 'Não há resposta transitória em processamento. Para cancelar um fluxo longo, diga “cancelar missão <ID>”.'
        )
        _schedule_send(loop, gateway, source, answer, trace)
        return {'action': 'skip', 'reason': 'explicit-cancel'}

    is_time = bool(TIME_RE.search(text))
    tier = _classify_complexity(text, is_cron=is_time)
    if not _PENDING.acquire(blocking=False):
        _schedule_send(
            loop,
            gateway,
            source,
            'Tenho muitos fluxos locais em andamento agora. Tente novamente em alguns instantes.',
            trace,
        )
        return {'action': 'skip', 'reason': 'capacity-full'}

    work = Work(gateway, source, text, loop, trace, tier, is_time, time.perf_counter())
    _EXECUTOR.submit(_process, work)
    logger.info('fastpath trace=%s dispatched tier=%s time=%s chat=%s', trace, tier, is_time, _chat_key(source))
    return {'action': 'skip', 'reason': 'hermes-core-concurrent-dispatch'}


def register(ctx):
    ctx.register_hook('pre_gateway_dispatch', pre_gateway_dispatch)
    logger.warning('HERMES CORE FASTPATH registered v2.0 multi-flow concurrent')
