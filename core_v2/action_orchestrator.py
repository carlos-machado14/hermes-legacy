#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path.home() / '.hermes' / 'core-v2'
STATE = ROOT / 'state'
LOGS = ROOT / 'logs'
PENDING_FILE = STATE / 'pending_actions.json'
JOURNAL_FILE = LOGS / 'action_journal.jsonl'
POLICY_FILE = STATE / 'operational_policy.json'

DEFAULT_POLICY = {
    'language': 'pt-BR',
    'confirm_mutations': True,
    'confirm_destructive': True,
    'fresh_data_requires_tool': True,
    'max_safe_retries': 1,
    'allow_readonly_without_confirmation': True,
}

CONFIRM_RE = re.compile(r'^\s*(sim|confirmo|confirmado|pode|pode fazer|pode executar|execute|faz|faça|ok|correto|esta correto|está correto)\s*[.!]?\s*$', re.I)
CANCEL_RE = re.compile(r'^\s*(não|nao|cancela|cancelar|esquece|deixa pra la|deixa pra lá|pare|para)\s*[.!]?\s*$', re.I)
UNDO_RE = re.compile(r'\b(desfaz|desfazer|volta|reverte|reverter|undo)\b', re.I)

READONLY_RESEARCH_HINTS = (
    'pesquise', 'pesquisar', 'procure', 'procurar', 'busque', 'buscar', 'encontre', 'encontrar',
    'colete', 'coletar', 'levante', 'levantar', 'investigue', 'investigar', 'analise', 'analisar',
    'empresa', 'empresas', 'lead', 'leads', 'site', 'sem site', 'dados públicos', 'dados publicos',
)
CURRENT_HINTS = (
    'agora', 'hoje', 'neste momento', 'atual', 'atualizado', 'temperatura', 'clima', 'vai chover',
    'cotação', 'cotacao', 'notícias', 'noticias', 'placar', 'resultado de hoje',
)
MUTATION_HINTS = (
    'reinicie', 'reiniciar', 'restart', 'inicie o serviço', 'suba o serviço', 'pare o serviço',
    'deploy', 'publique', 'publicar', 'remova', 'remover', 'apague', 'apagar', 'delete',
    'crie issue', 'criar issue', 'abra issue', 'crie uma issue', 'faça deploy', 'faca deploy',
)


@dataclass
class ActionPlan:
    id: str
    request: str
    kind: str
    tool: str
    summary: str
    params: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    destructive: bool = False
    reversible: bool = False
    undo: dict[str, Any] | None = None
    created_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat())


def _load_json(path: Path, default: Any) -> Any:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data
    except Exception:
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def policy() -> dict[str, Any]:
    current = _load_json(POLICY_FILE, {})
    merged = dict(DEFAULT_POLICY)
    if isinstance(current, dict):
        merged.update(current)
    if merged != current:
        _save_json(POLICY_FILE, merged)
    return merged


def _chat_key() -> str:
    return (os.getenv('HERMES_CHAT_KEY') or 'default').strip() or 'default'


def _pending_all() -> dict[str, Any]:
    data = _load_json(PENDING_FILE, {})
    return data if isinstance(data, dict) else {}


def _pending_get(key: str) -> dict[str, Any] | None:
    row = _pending_all().get(key)
    return row if isinstance(row, dict) else None


def _pending_set(key: str, plan: ActionPlan) -> None:
    data = _pending_all()
    data[key] = asdict(plan)
    _save_json(PENDING_FILE, data)


def _pending_clear(key: str) -> None:
    data = _pending_all()
    data.pop(key, None)
    _save_json(PENDING_FILE, data)


def _journal(event: str, plan: ActionPlan | dict[str, Any], **extra: Any) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    payload = {
        'ts': datetime.now().astimezone().isoformat(),
        'event': event,
        'chat_key': _chat_key(),
        'plan': asdict(plan) if isinstance(plan, ActionPlan) else plan,
        **extra,
    }
    with JOURNAL_FILE.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + '\n')


def _last_successful_reversible() -> dict[str, Any] | None:
    if not JOURNAL_FILE.exists():
        return None
    try:
        lines = JOURNAL_FILE.read_text(encoding='utf-8').splitlines()[-200:]
    except Exception:
        return None
    key = _chat_key()
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get('chat_key') != key or row.get('event') != 'executed' or not row.get('ok'):
            continue
        plan = row.get('plan') or {}
        if plan.get('reversible') and plan.get('undo'):
            return plan
    return None


def _extract_service(text: str) -> str | None:
    low = text.casefold()
    aliases = {
        'gateway': 'hermes-gateway.service',
        'fast router': 'hermes-fast-router.service',
        'router': 'hermes-fast-router.service',
        'health': 'hermes-core-health.service',
        'watcher': 'hermes-core-watchers.service',
        'api': 'hermes-core-api.service',
    }
    for key, service in aliases.items():
        if key in low:
            return service
    match = re.search(r'\b([\w.-]+\.service)\b', text)
    return match.group(1) if match else None


def _is_readonly_research(text: str) -> bool:
    low = text.casefold()
    has_research = any(h in low for h in READONLY_RESEARCH_HINTS)
    has_mutation = any(h in low for h in MUTATION_HINTS)
    schedule_words = ('rotina', 'agende', 'agendar', 'todo dia', 'diariamente', 'me lembre', 'lembrete')
    return has_research and not has_mutation and not any(w in low for w in schedule_words)


def _is_current_info(text: str) -> bool:
    low = text.casefold()
    return any(h in low for h in CURRENT_HINTS)


def _is_mutation(text: str) -> bool:
    low = text.casefold()
    return any(h in low for h in MUTATION_HINTS)


def _plan(text: str) -> ActionPlan | None:
    clean = str(text or '').strip()
    low = clean.casefold()
    if not clean:
        return None

    if _is_readonly_research(clean) or _is_current_info(clean):
        return ActionPlan(
            id=uuid.uuid4().hex[:12], request=clean, kind='read', tool='web',
            summary=f'Pesquisar dados atuais e responder com fontes: {clean}',
            requires_confirmation=False,
        )

    if _is_mutation(clean):
        service = _extract_service(clean)
        if service and any(k in low for k in ('reinicie', 'reiniciar', 'restart')):
            return ActionPlan(
                id=uuid.uuid4().hex[:12], request=clean, kind='mutation', tool='service_restart',
                summary=f'Reiniciar {service} e validar se voltou ativo.',
                params={'service': service}, requires_confirmation=True,
                reversible=False,
            )
        # Foundation for external/developer actions: do not invent execution.
        return ActionPlan(
            id=uuid.uuid4().hex[:12], request=clean, kind='mutation', tool='delegated',
            summary=f'Executar a ação solicitada com validação final: {clean}',
            requires_confirmation=True,
            missing=[],
        )
    return None


def _format_confirmation(plan: ActionPlan) -> str:
    lines = [
        'Entendi o que você quer fazer. Antes de executar, confirma este plano:',
        f'• Ação: {plan.summary}',
    ]
    if plan.missing:
        lines.append('• Ainda falta: ' + ', '.join(plan.missing))
        lines.append('Me passe esses dados e eu atualizo o plano antes de executar.')
    else:
        lines.append('• Depois eu valido se realmente deu certo.')
        lines.append('Está correto? Responda “sim” para executar ou diga o que quer alterar.')
    return '\n'.join(lines)


def _execute_web(plan: ActionPlan) -> tuple[bool, str]:
    from web_research import format_research, research, research_company
    low = plan.request.casefold()
    try:
        if any(k in low for k in ('empresa', 'empresas', 'lead', 'leads', 'sem site')):
            report = research_company(plan.request, limit=6)
        else:
            report = research(plan.request, limit=8)
        text = format_research(report)
        ok = bool(text and 'Nenhum resultado encontrado' not in text)
        return ok, text
    except Exception as exc:
        return False, f'Falha ao pesquisar dados atuais: {exc}'


def _execute_restart(plan: ActionPlan) -> tuple[bool, str]:
    from action_executor import execute
    result = execute('restart_service', {'service': plan.params.get('service')})
    ok = bool(result.get('ok'))
    if ok:
        return True, f"✅ {plan.params.get('service')} reiniciado e validado como ativo."
    return False, 'Não consegui reiniciar/validar o serviço: ' + str(result.get('error') or result.get('stderr') or result)


def _execute_delegated(plan: ActionPlan, llm: Callable[[str], str] | None) -> tuple[bool, str]:
    # Never claim an external mutation occurred without a real executor.
    if llm is None:
        return False, 'Essa ação ainda não possui um executor seguro conectado. Não executei nada.'
    try:
        response = llm(
            'Planeje a execução abaixo SEM afirmar que executou ações externas. '
            'Liste ferramentas/dados necessários e como validar o resultado. Pedido: ' + plan.request
        )
        return False, response
    except Exception as exc:
        return False, f'Não consegui preparar a execução: {exc}'


def _execute(plan: ActionPlan, llm: Callable[[str], str] | None = None) -> tuple[bool, str]:
    executors = {
        'web': lambda: _execute_web(plan),
        'service_restart': lambda: _execute_restart(plan),
        'delegated': lambda: _execute_delegated(plan, llm),
    }
    fn = executors.get(plan.tool)
    if fn is None:
        return False, 'Não existe executor seguro para essa ação ainda.'

    retries = max(0, int(policy().get('max_safe_retries') or 0)) if plan.kind == 'read' else 0
    last: tuple[bool, str] = (False, 'Falha desconhecida.')
    for attempt in range(retries + 1):
        last = fn()
        if last[0]:
            break
        if attempt < retries:
            time.sleep(0.4)
    _journal('executed', plan, ok=last[0], result=last[1][:3000])
    return last


def _undo() -> str:
    plan = _last_successful_reversible()
    if not plan:
        return 'Não encontrei uma ação recente que eu consiga desfazer com segurança.'
    undo = plan.get('undo') or {}
    tool = undo.get('tool')
    if tool == 'service_restart':
        return 'Reinício de serviço não possui desfazer automático seguro.'
    return 'A última ação registrada não possui um procedimento de desfazer disponível.'


def _merge_revision(pending: dict[str, Any], text: str) -> ActionPlan:
    plan = ActionPlan(**{k: pending[k] for k in ActionPlan.__dataclass_fields__ if k in pending})
    # Keep original request but incorporate user correction for replanning.
    replanned = _plan(plan.request + '\nALTERAÇÃO DO USUÁRIO: ' + text)
    if replanned and replanned.tool == plan.tool:
        replanned.id = plan.id
        return replanned
    plan.request += '\nAlteração: ' + text
    plan.summary = plan.summary.rstrip('.') + f'. Ajuste solicitado: {text}'
    return plan


def handle(text: str, llm: Callable[[str], str] | None = None) -> str | None:
    clean = str(text or '').strip()
    if not clean:
        return None
    key = _chat_key()

    if UNDO_RE.search(clean):
        return _undo()

    pending = _pending_get(key)
    if pending:
        if CANCEL_RE.match(clean):
            _pending_clear(key)
            _journal('cancelled', pending)
            return 'Certo. Não executei a ação pendente.'
        if CONFIRM_RE.match(clean):
            plan = ActionPlan(**{k: pending[k] for k in ActionPlan.__dataclass_fields__ if k in pending})
            if plan.missing:
                return 'Ainda faltam dados antes da confirmação: ' + ', '.join(plan.missing)
            ok, result = _execute(plan, llm)
            _pending_clear(key)
            return result
        plan = _merge_revision(pending, clean)
        _pending_set(key, plan)
        _journal('revised', plan)
        return _format_confirmation(plan)

    plan = _plan(clean)
    if plan is None:
        return None

    _journal('planned', plan)
    if plan.requires_confirmation or (plan.destructive and policy().get('confirm_destructive', True)):
        _pending_set(key, plan)
        return _format_confirmation(plan)

    ok, result = _execute(plan, llm)
    return result


def action_status() -> str:
    pending = _pending_get(_chat_key())
    if pending:
        return 'Há uma ação aguardando confirmação: ' + str(pending.get('summary') or pending.get('request') or '')
    return 'Não há ação pendente nesta conversa.'
