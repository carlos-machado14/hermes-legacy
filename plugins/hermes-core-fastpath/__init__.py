from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger('hermes_core_fastpath')


@dataclass
class Work:
    gateway: Any
    source: Any
    text: str
    loop: asyncio.AbstractEventLoop
    trace_id: str
    enqueued_at: float


_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(2, min(12, int(os.getenv('HERMES_GATEWAY_WORKERS', '6')))),
    thread_name_prefix='hermes-semantic-gateway',
)
_PENDING = threading.BoundedSemaphore(max(20, int(os.getenv('HERMES_GATEWAY_PENDING', '100'))))
_TIMEOUT = max(15, int(os.getenv('HERMES_GATEWAY_TIMEOUT', '90')))
_PROC_LOCK = threading.Lock()
_ACTIVE_PROCS: dict[str, subprocess.Popen[str]] = {}


def _trace_id() -> str:
    return uuid.uuid4().hex[:12]


def _chat_key(source: Any) -> str:
    platform = str(getattr(getattr(source, 'platform', None), 'value', '') or '').strip().lower()
    chat_id = str(getattr(source, 'chat_id', '') or '').strip()
    return f'{platform}:{chat_id}' if chat_id else ''


def _register_proc(trace: str, proc: subprocess.Popen[str] | None) -> None:
    with _PROC_LOCK:
        if proc is None:
            _ACTIVE_PROCS.pop(trace, None)
        else:
            _ACTIVE_PROCS[trace] = proc


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
        logger.warning('gateway channel save failed: %s', exc)


def _run_core(work: Work) -> str:
    root = Path.home() / '.hermes' / 'core-v2'
    py = root / 'venv' / 'bin' / 'python'
    core = root / 'core_entry.py'
    env = os.environ.copy()
    env['HERMES_TRACE_ID'] = work.trace_id
    env['HERMES_SOURCE_PLATFORM'] = str(getattr(getattr(work.source, 'platform', None), 'value', '') or '')
    env['HERMES_SOURCE_CHAT_ID'] = str(getattr(work.source, 'chat_id', '') or '')
    env['HERMES_SOURCE_USER_ID'] = str(getattr(work.source, 'user_id', '') or '')
    proc = subprocess.Popen(
        [str(py), str(core), work.text],
        cwd=str(root),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _register_proc(work.trace_id, proc)
    try:
        stdout, stderr = proc.communicate(timeout=_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=2)
        except Exception:
            proc.kill()
            stdout, stderr = proc.communicate()
        return 'Não consegui responder dentro do tempo esperado. Tente novamente em alguns instantes.'
    finally:
        _register_proc(work.trace_id, None)
    if proc.returncode != 0:
        detail = (stderr or stdout or '')[-500:].strip()
        return f'⚠️ Não consegui concluir essa solicitação. {detail}'
    return (stdout or '').strip() or 'Não encontrei uma resposta confiável para isso agora.'


def _split_message(text: str, limit: int = 3600) -> list[str]:
    text = (text or '').strip()
    if not text:
        return ['Não encontrei uma resposta confiável para isso agora.']
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind('\n', 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(' ', 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    if len(chunks) <= 1:
        return chunks
    total = len(chunks)
    return [f'[{index}/{total}]\n{chunk}' for index, chunk in enumerate(chunks, 1)]


async def _send_all(adapter: Any, chat_id: Any, chunks: list[str], trace: str) -> None:
    for index, chunk in enumerate(chunks, 1):
        await adapter.send(chat_id, chunk)
        logger.info('semantic-gateway trace=%s sent part=%s/%s chars=%s', trace, index, len(chunks), len(chunk))
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
            task.add_done_callback(lambda done: logger.error('semantic-gateway send failed trace=%s err=%s', trace, done.exception()) if done.exception() else None)
        except Exception:
            logger.exception('semantic-gateway send scheduling failed trace=%s', trace)

    loop.call_soon_threadsafe(submit)


def _process(work: Work) -> None:
    try:
        reply = _run_core(work)
        _schedule_send(work.loop, work.gateway, work.source, reply, work.trace_id)
        logger.info('semantic-gateway trace=%s completed ms=%.1f chat=%s', work.trace_id, (time.time() - work.enqueued_at) * 1000, _chat_key(work.source))
    except Exception as exc:
        logger.exception('semantic-gateway trace=%s failed', work.trace_id)
        _schedule_send(work.loop, work.gateway, work.source, f'⚠️ Não consegui concluir essa solicitação. {exc}', work.trace_id)
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

    if not _PENDING.acquire(blocking=False):
        _schedule_send(loop, gateway, source, 'Tenho muitos fluxos em andamento agora. Tente novamente em alguns instantes.', _trace_id())
        return {'action': 'skip', 'reason': 'semantic-gateway-busy'}

    trace = _trace_id()
    work = Work(
        gateway=gateway,
        source=source,
        text=text,
        loop=loop,
        trace_id=trace,
        enqueued_at=time.time(),
    )
    _EXECUTOR.submit(_process, work)
    logger.info('semantic-gateway trace=%s dispatched chat=%s', trace, _chat_key(source))
    return {'action': 'skip', 'reason': 'semantic-core-dispatch'}


def register(ctx):
    ctx.register_hook('pre_gateway_dispatch', pre_gateway_dispatch)
    logger.warning('HERMES semantic gateway registered v3.0')
