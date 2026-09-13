from __future__ import annotations

import asyncio
import base64
import logging
import re
import subprocess
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


def _authorized(gateway: Any, source: Any) -> bool:
    try:
        result = bool(gateway._is_user_authorized_for_source(source))
        logger.info("fastpath auth=%s platform=%s chat=%s user=%s", result, getattr(getattr(source, 'platform', None), 'value', None), getattr(source, 'chat_id', None), getattr(source, 'user_id', None))
        return result
    except Exception as exc:
        logger.exception("fastpath auth check failed: %s", exc)
        return False


def _run_core(text: str) -> str:
    root = Path.home() / '.hermes' / 'core-v2'
    py = root / 'venv' / 'bin' / 'python'
    core = root / 'hermes_core.py'
    logger.info("fastpath -> core text=%r", text[:180])
    proc = subprocess.run(
        [str(py), str(core), text],
        text=True,
        capture_output=True,
        timeout=40,
        cwd=str(root),
    )
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
    proc = subprocess.run(
        [str(py), str(manager), '--text-b64', encoded],
        text=True,
        capture_output=True,
        timeout=30,
        cwd=str(root),
    )
    raw = (proc.stdout or '').strip()
    logger.info("fastpath cron rc=%s stdout_len=%s stderr_len=%s", proc.returncode, len(raw), len(proc.stderr or ''))
    if proc.returncode != 0:
        return f"⚠️ Cron Manager retornou erro: {(proc.stderr or raw)[-800:].strip()}"
    marker = 'HERMES_CRON_RESULT:'
    if marker in raw:
        return raw.rsplit(marker, 1)[-1].strip()
    return raw or 'Cron Manager concluiu sem mensagem.'


def _schedule_send(gateway: Any, source: Any, text: str) -> None:
    try:
        adapter = gateway._adapter_for_source(source)
        if adapter is None:
            logger.error("fastpath send failed: adapter ausente")
            return
        coro = adapter.send(source.chat_id, text)
        try:
            asyncio.get_running_loop().create_task(coro)
            logger.info("fastpath reply scheduled on running loop chat=%s chars=%s", source.chat_id, len(text))
        except RuntimeError:
            asyncio.run(coro)
            logger.info("fastpath reply sent with asyncio.run chat=%s chars=%s", source.chat_id, len(text))
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
        logger.info("fastpath allow: empty text/source")
        return None
    if not _authorized(gateway, source):
        logger.info("fastpath allow: unauthorized")
        return None

    # Preserve explicit Hermes/Gateway slash commands such as /reset and /compress.
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
    logger.warning("HERMES CORE FASTPATH v1.1.0 REGISTERED")
    ctx.register_hook('pre_gateway_dispatch', pre_gateway_dispatch)
