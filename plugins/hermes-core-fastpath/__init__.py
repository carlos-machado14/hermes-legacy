from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("hermes_core_fastpath")

CRON_RE = re.compile(
    r"(?:\b(?:crie|criar|adicione|adicionar|agende|agendar|pause|pausar|pare|parar|"
    r"retome|retomar|remova|remover|apague|apagar|rode|rodar|execute|executar)\b.*"
    r"\b(?:rotina|cron|lembrete|todo dia|todos os dias|diariamente|a cada|not[ií]cias?)\b|"
    r"\b(?:me lembre|lembre-me)\b|"
    r"\b(?:todo dia|todos os dias|diariamente|a cada\s+\d+\s+(?:minutos?|horas?|dias?))\b.*"
    r"\b(?:mande|envie|avise|lembre|not[ií]cias?)\b|"
    r"\b(?:quais rotinas|minhas rotinas|listar rotinas|liste as rotinas|listar crons)\b)",
    re.IGNORECASE,
)


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
        logger.info("fastpath remembered proactive channel platform=%s chat=%s", platform, chat_id)
    except Exception as exc:
        logger.warning("fastpath could not remember proactive channel: %s", exc)


def _run_core(text: str) -> str:
    root = Path.home() / '.hermes' / 'core-v2'
    py = root / 'venv' / 'bin' / 'python'
    core = root / 'core_entry.py'
    logger.info("fastpath -> conversational core text=%r", text[:180])
    proc = subprocess.run([str(py), str(core), text], text=True, capture_output=True, timeout=55, cwd=str(root))
    logger.info("fastpath core rc=%s stdout_len=%s stderr_len=%s", proc.returncode, len(proc.stdout or ''), len(proc.stderr or ''))
    if proc.returncode != 0:
        return f"⚠️ Hermes Core retornou erro: {(proc.stderr or proc.stdout)[-800:].strip()}"
    return (proc.stdout or '').strip() or 'Hermes Core concluiu a ação sem mensagem.'


def _run_cron(text: str) -> str:
    root = Path.home() / '.hermes' / 'core-v2'
    py = root / 'venv' / 'bin' / 'python'
    manager = root / 'cron_manager.py'
    encoded = base64.urlsafe_b64encode(text.encode('utf-8')).decode('ascii')
    logger.info("fastpath -> cron text=%r", text[:180])
    proc = subprocess.run([str(py), str(manager), '--text-b64', encoded], text=True, capture_output=True, timeout=30, cwd=str(root))
    raw = (proc.stdout or '').strip()
    logger.info("fastpath cron rc=%s stdout_len=%s stderr_len=%s", proc.returncode, len(raw), len(proc.stderr or ''))
    if proc.returncode != 0:
        return f"⚠️ Cron Manager retornou erro: {(proc.stderr or raw)[-800:].strip()}"
    marker = 'HERMES_CRON_RESULT:'
    if marker in raw:
        return raw.rsplit(marker, 1)[-1].strip()
    return raw or 'Cron Manager concluiu sem mensagem.'


def _split_message(text: str, limit: int = 3600) -> list[str]:
    text = (text or '').strip()
    if not text:
        return ['Hermes Core concluiu a ação sem mensagem.']
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


async def _send_all(adapter: Any, chat_id: Any, chunks: list[str]) -> None:
    for index, chunk in enumerate(chunks, 1):
        await adapter.send(chat_id, chunk)
        logger.info("fastpath reply chunk sent chat=%s part=%s/%s chars=%s", chat_id, index, len(chunks), len(chunk))
        if index < len(chunks):
            await asyncio.sleep(0.15)


def _schedule_send(gateway: Any, source: Any, text: str) -> None:
    try:
        adapter = gateway._adapter_for_source(source)
        if adapter is None:
            logger.error("fastpath send failed: adapter ausente")
            return
        chunks = _split_message(text)
        coro = _send_all(adapter, source.chat_id, chunks)
        try:
            asyncio.get_running_loop().create_task(coro)
            logger.info("fastpath reply scheduled chat=%s chunks=%s chars=%s", source.chat_id, len(chunks), len(text))
        except RuntimeError:
            asyncio.run(coro)
            logger.info("fastpath reply sent with asyncio.run chat=%s chunks=%s chars=%s", source.chat_id, len(chunks), len(text))
    except Exception as exc:
        logger.exception("fastpath send failed: %s", exc)


def pre_gateway_dispatch(**kwargs):
    event = kwargs.get('event')
    gateway = kwargs.get('gateway')
    if event is None or gateway is None:
        logger.warning("fastpath hook invoked without event/gateway")
        return None

    source = getattr(event, 'source', None)
    text = str(getattr(event, 'text', '') or '').strip()
    logger.info("fastpath inbound text=%r platform=%s chat=%s", text[:180], getattr(getattr(source, 'platform', None), 'value', None) if source else None, getattr(source, 'chat_id', None) if source else None)

    if not text or source is None:
        return None
    if not _authorized(gateway, source):
        logger.info("fastpath allow legacy path: sender not authorized by compatibility gate")
        return None

    _remember_channel(source)
    if text.startswith('/'):
        logger.info("fastpath allow slash command=%r", text[:80])
        return None

    try:
        reply = _run_cron(text) if CRON_RE.search(text) else _run_core(text)
    except subprocess.TimeoutExpired:
        logger.exception("fastpath local execution timeout")
        reply = '⚠️ O Hermes Core excedeu o tempo limite. Tente novamente em alguns segundos.'
    except Exception as exc:
        logger.exception("fastpath local execution failed: %s", exc)
        reply = f'⚠️ Falha no Hermes Core: {exc}'

    _schedule_send(gateway, source, reply)
    logger.info("fastpath SKIP legacy dispatch reason=hermes-core-all-messages")
    return {'action': 'skip', 'reason': 'hermes-core-all-messages'}


def register(ctx):
    logger.warning("HERMES CORE FASTPATH v1.3.0 REGISTERED")
    ctx.register_hook('pre_gateway_dispatch', pre_gateway_dispatch)
