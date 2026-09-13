from __future__ import annotations

import asyncio
import base64
import re
import subprocess
from pathlib import Path
from typing import Any

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
        return bool(gateway._is_user_authorized_for_source(source))
    except Exception:
        return False


def _run_core(text: str) -> str:
    root = Path.home() / '.hermes' / 'core-v2'
    py = root / 'venv' / 'bin' / 'python'
    core = root / 'hermes_core.py'
    proc = subprocess.run(
        [str(py), str(core), text],
        text=True,
        capture_output=True,
        timeout=40,
        cwd=str(root),
    )
    if proc.returncode != 0:
        return f"⚠️ Hermes Core retornou erro: {(proc.stderr or proc.stdout)[-800:].strip()}"
    return (proc.stdout or '').strip() or 'Hermes Core concluiu a ação sem mensagem.'


def _run_cron(text: str) -> str:
    root = Path.home() / '.hermes' / 'core-v2'
    py = root / 'venv' / 'bin' / 'python'
    manager = root / 'cron_manager.py'
    encoded = base64.urlsafe_b64encode(text.encode('utf-8')).decode('ascii')
    proc = subprocess.run(
        [str(py), str(manager), '--text-b64', encoded],
        text=True,
        capture_output=True,
        timeout=30,
        cwd=str(root),
    )
    raw = (proc.stdout or '').strip()
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
            return
        coro = adapter.send(source.chat_id, text)
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            asyncio.run(coro)
    except Exception:
        return


def pre_gateway_dispatch(**kwargs):
    event = kwargs.get('event')
    gateway = kwargs.get('gateway')
    if event is None or gateway is None:
        return None

    source = getattr(event, 'source', None)
    text = str(getattr(event, 'text', '') or '').strip()
    if not text or source is None or not _authorized(gateway, source):
        return None

    # Preserve explicit Hermes/Gateway slash commands such as /reset and /compress.
    if text.startswith('/'):
        return None

    # Every normal authorized Telegram message goes through Hermes Core first.
    # This prevents the legacy gateway session/compression path from bypassing
    # personal memory and from loading an outdated/slow model directly.
    try:
        reply = _run_cron(text) if CRON_RE.search(text) else _run_core(text)
    except subprocess.TimeoutExpired:
        reply = '⚠️ O Hermes Core excedeu o tempo limite. Tente novamente em alguns segundos.'
    except Exception as exc:
        reply = f'⚠️ Falha no Hermes Core: {exc}'

    _schedule_send(gateway, source, reply)
    return {'action': 'skip', 'reason': 'hermes-core-all-messages'}


def register(ctx):
    ctx.register_hook('pre_gateway_dispatch', pre_gateway_dispatch)
