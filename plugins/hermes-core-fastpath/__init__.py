from __future__ import annotations

import asyncio
import base64
import re
import subprocess
from pathlib import Path
from typing import Any

CORE_RE = re.compile(
    r"(?:\b(?:status|sa[uú]de|health)\b.*\b(?:vps|hermes|servi[cç]os?|projeto)\b|"
    r"\b(?:verifique|verificar)\b.*\b(?:vps|servi[cç]os?|crons?|projeto)\b|"
    r"\b(?:corrija tudo|corrigir tudo|recupere os servi[cç]os|auto[- ]?recovery)\b|"
    r"\b(?:o que (?:voc[eê] )?corrigiu|hist[oó]rico (?:operacional|de corre[cç][oõ]es))\b|"
    r"\b(?:reinicie|reiniciar)\b.*\b(?:gateway|router|llm|modelo|health|monitor|watchers?|api|projeto)\b|"
    r"\b(?:quais ferramentas|listar ferramentas|ferramentas|quais skills|habilidades do hermes)\b|"
    r"\b(?:quais projetos|listar projetos|liste os projetos|meus projetos)\b|"
    r"\b(?:cadastre|cadastrar|adicione|adicionar|registre|registrar|remova|remover|apague|apagar|monitore|monitorar)\b.*\bprojeto\b|"
    r"\b(?:status|como est[aá])\b.*\bprojeto\b|"
    r"\b(?:incidentes|incidentes recentes|problemas recentes|falhas recentes)\b|"
    r"\b(?:containers|docker ps|status do docker)\b|"
    r"\b(?:logs? do (?:gateway|llm|modelo|router))\b|"
    r"\b(?:meus objetivos|listar objetivos|quais objetivos|crie objetivo|criar objetivo|novo objetivo|plano do objetivo|planeje objetivo|concluir objetivo|finalizar objetivo)\b|"
    r"\b(?:minhas tarefas|listar tarefas|tarefas pendentes|crie tarefa|criar tarefa|nova tarefa|concluir tarefa|marque tarefa)\b|"
    r"\b(?:quero ganhar|quero faturar|meta de renda|meta de receita|oportunidades(?: para ganhar dinheiro| de renda| de neg[oó]cio)?|minhas oportunidades)\b|"
    r"\b(?:lembre que eu sei|eu sei|lembre que|meu perfil|perfil pessoal|o que voc[eê] sabe sobre mim)\b|"
    r"\b(?:pesquise|pesquisar)\b)",
    re.IGNORECASE,
)

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
    try: return bool(gateway._is_user_authorized_for_source(source))
    except Exception: return False


def _run_core(text: str) -> str:
    root = Path.home() / '.hermes' / 'core-v2'; py = root / 'venv' / 'bin' / 'python'; core = root / 'hermes_core.py'
    proc = subprocess.run([str(py), str(core), text], text=True, capture_output=True, timeout=25, cwd=str(root))
    if proc.returncode != 0: return f"⚠️ Hermes Core retornou erro: {(proc.stderr or proc.stdout)[-600:].strip()}"
    return (proc.stdout or '').strip() or 'Hermes Core concluiu a ação sem mensagem.'


def _run_cron(text: str) -> str:
    root = Path.home() / '.hermes' / 'core-v2'; py = root / 'venv' / 'bin' / 'python'; manager = root / 'cron_manager.py'
    encoded = base64.urlsafe_b64encode(text.encode('utf-8')).decode('ascii')
    proc = subprocess.run([str(py), str(manager), '--text-b64', encoded], text=True, capture_output=True, timeout=25, cwd=str(root))
    raw = (proc.stdout or '').strip()
    if proc.returncode != 0: return f"⚠️ Cron Manager retornou erro: {(proc.stderr or raw)[-600:].strip()}"
    marker = 'HERMES_CRON_RESULT:'
    if marker in raw: return raw.rsplit(marker, 1)[-1].strip()
    return raw or 'Cron Manager concluiu sem mensagem.'


def _schedule_send(gateway: Any, source: Any, text: str) -> None:
    try:
        adapter = gateway._adapter_for_source(source)
        if adapter is None: return
        asyncio.get_running_loop().create_task(adapter.send(source.chat_id, text))
    except Exception: return


def pre_gateway_dispatch(**kwargs):
    event = kwargs.get('event'); gateway = kwargs.get('gateway')
    if event is None or gateway is None: return None
    source = getattr(event, 'source', None); text = str(getattr(event, 'text', '') or '').strip()
    if not text or source is None or not _authorized(gateway, source): return None
    is_cron = bool(CRON_RE.search(text)); is_core = bool(CORE_RE.search(text))
    if not (is_cron or is_core): return None
    try: reply = _run_cron(text) if is_cron else _run_core(text)
    except subprocess.TimeoutExpired: reply = '⚠️ A ação local excedeu 25s e foi interrompida.'
    except Exception as exc: reply = f'⚠️ Falha no fastpath local: {exc}'
    _schedule_send(gateway, source, reply)
    return {'action': 'skip', 'reason': 'hermes-core-fastpath'}


def register(ctx):
    ctx.register_hook('pre_gateway_dispatch', pre_gateway_dispatch)
