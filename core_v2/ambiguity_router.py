#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

STATE = Path.home() / '.hermes' / 'core-v2' / 'state'
PENDING_FILE = STATE / 'pending_choices.json'
TTL_SECONDS = 15 * 60


def _norm(text: str) -> str:
    raw = unicodedata.normalize('NFKD', str(text or ''))
    raw = ''.join(ch for ch in raw if not unicodedata.combining(ch)).casefold()
    raw = re.sub(r'[^a-z0-9]+', ' ', raw)
    return re.sub(r'\s+', ' ', raw).strip()


def _source_key() -> str:
    platform = (os.getenv('HERMES_SOURCE_PLATFORM') or 'local').strip().lower()
    chat_id = (os.getenv('HERMES_SOURCE_CHAT_ID') or '').strip()
    user_id = (os.getenv('HERMES_SOURCE_USER_ID') or '').strip()
    return f'{platform}:{chat_id or user_id or "default"}'


def _load() -> dict[str, Any]:
    try:
        data = json.loads(PENDING_FILE.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return {}
    except Exception:
        return {}
    now = int(time.time())
    changed = False
    for key in list(data):
        row = data.get(key)
        if not isinstance(row, dict) or int(row.get('expires_at') or 0) <= now:
            data.pop(key, None)
            changed = True
    if changed:
        _save(data)
    return data


def _save(data: dict[str, Any]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = PENDING_FILE.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(PENDING_FILE)


def _tokens(text: str) -> set[str]:
    stop = {
        'cancele','cancelar','cancela','remova','remover','apague','apagar','exclua','excluir',
        'pause','pausar','pare','parar','retome','retomar','reative','reativar','encerre','encerrei',
        'a','o','as','os','um','uma','de','da','do','das','dos','minha','meu','minhas','meus',
        'rotina','rotinas','lembrete','lembretes','agenda','evento','eventos','compromisso','compromissos',
        'conta','contas','financeiro','financeira','gasto','gastos','assinatura','assinaturas',
        'antiga','antigo','velha','velho','essa','esse','isso','por','favor',
    }
    return {x for x in _norm(text).split() if x and x not in stop and len(x) >= 2}


def _score(query: set[str], label: str) -> int:
    if not query:
        return 0
    target = set(_norm(label).split())
    overlap = len(query & target)
    if not overlap:
        return 0
    score = overlap * 3
    if query <= target:
        score += 4
    if target <= query:
        score += 2
    return score


def _time_candidates(text: str, *, preferred_id: str | None = None) -> list[dict[str, Any]]:
    from time_store import list_schedules

    query = _tokens(text)
    rows: list[tuple[int, dict[str, Any]]] = []
    for item in list_schedules(status='active', limit=200):
        item_id = str(item.get('id') or '')
        label = str(item.get('message') or item.get('title') or '')
        score = _score(query, label)
        if preferred_id and item_id == preferred_id:
            score += 20
        if score > 0:
            rows.append((score, item))
    rows.sort(key=lambda pair: pair[0], reverse=True)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, item in rows[:5]:
        item_id = str(item.get('id') or '')
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        out.append({
            'domain': 'time',
            'action': 'remove',
            'id': item_id,
            'label': str(item.get('message') or item.get('title') or 'Lembrete'),
            'kind': str(item.get('kind') or 'lembrete'),
        })
    return out


def _finance_candidates(text: str) -> list[dict[str, Any]]:
    try:
        from finance_manager import load
    except Exception:
        return []
    data = load()
    query = _tokens(text)
    rows: list[tuple[int, str, dict[str, Any]]] = []
    for kind, key in (('conta', 'expenses'), ('assinatura', 'subscriptions'), ('grupo de assinaturas', 'subscription_groups')):
        for row in data.get(key, []) if isinstance(data.get(key), list) else []:
            if not isinstance(row, dict) or not row.get('active', True):
                continue
            name = str(row.get('name') or '')
            score = _score(query, name)
            if score > 0:
                rows.append((score, kind, row))
    rows.sort(key=lambda item: item[0], reverse=True)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, kind, row in rows[:5]:
        name = str(row.get('name') or '')
        key = _norm(name)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({
            'domain': 'finance',
            'action': 'deactivate',
            'name': name,
            'label': name,
            'kind': kind,
        })
    return out


def _action_is_destructive(text: str) -> bool:
    low = _norm(text)
    words = ('cancele','cancelar','cancela','remova','remover','apague','apagar','exclua','excluir','pare','parar','pause','pausar','encerre','encerrei','quitei')
    return any(re.search(rf'\b{re.escape(word)}\b', low) for word in words)


def maybe_prompt(
    text: str,
    *,
    intended_domain: str | None = None,
    intended_action: str | None = None,
    intended_target_id: str | None = None,
) -> str | None:
    if not _action_is_destructive(text):
        return None

    candidates = _time_candidates(text, preferred_id=intended_target_id) + _finance_candidates(text)
    if intended_action:
        for item in candidates:
            if item['domain'] == intended_domain:
                item['action'] = intended_action

    # Only ask when there really is ambiguity: multiple viable targets or multiple domains.
    if len(candidates) <= 1:
        return None
    domains = {str(item.get('domain')) for item in candidates}
    if len(domains) == 1 and intended_target_id:
        matching = [item for item in candidates if str(item.get('id') or '') == intended_target_id]
        if len(matching) == 1:
            return None

    candidates = candidates[:6]
    now = int(time.time())
    data = _load()
    data[_source_key()] = {
        'created_at': now,
        'expires_at': now + TTL_SECONDS,
        'original_text': text,
        'options': candidates,
    }
    _save(data)

    lines = ['⚠️ Encontrei mais de uma interpretação possível. Não alterei nada ainda.', '', 'Qual delas você quis dizer?']
    for index, item in enumerate(candidates, 1):
        if item['domain'] == 'time':
            lines.append(f"{index}. Agenda — {item.get('kind')}: {item.get('label')} [ID {item.get('id')}]")
        else:
            lines.append(f"{index}. Financeiro — {item.get('kind')}: {item.get('label')}")
    lines += ['', f'Responda apenas com o número (1 a {len(candidates)}). A escolha expira em 15 minutos.']
    return '\n'.join(lines)


def _execute(option: dict[str, Any]) -> str:
    domain = str(option.get('domain') or '')
    action = str(option.get('action') or '')
    if domain == 'time':
        ref = str(option.get('id') or '')
        if action == 'pause':
            from time_store import pause
            item = pause(ref)
            return f"⏸️ Pausado: {item.get('message')}"
        if action == 'resume':
            from time_store import resume
            item = resume(ref)
            return f"▶️ Retomado: {item.get('message')}"
        from time_store import remove
        item = remove(ref)
        return f"🗑️ Removido da agenda: {item.get('message')}"

    if domain == 'finance':
        from finance_manager import load, save, summary
        data = load()
        wanted = _norm(str(option.get('name') or ''))
        for key in ('expenses', 'subscriptions', 'subscription_groups'):
            rows = data.get(key, [])
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and _norm(str(row.get('name') or '')) == wanted:
                    row['active'] = False
                    save(data, reason=f"desativado após confirmação explícita: {row.get('name')}")
                    return f"Marquei {row.get('name')} como encerrado/inativo após sua confirmação.\n\n{summary(data)}"
        return 'Não encontrei mais esse item financeiro. Nenhuma alteração foi feita.'

    return 'Essa opção não é mais válida. Nenhuma alteração foi feita.'


def resolve_pending(text: str) -> str | None:
    data = _load()
    key = _source_key()
    pending = data.get(key)
    if not isinstance(pending, dict):
        return None

    low = _norm(text)
    if low in {'cancelar escolha','cancele escolha','nenhuma','nenhum','deixa','deixe','voltar'}:
        data.pop(key, None)
        _save(data)
        return 'Certo. Cancelei a escolha e não alterei nada.'

    match = re.fullmatch(r'(?:opcao\s*)?(\d+)', low)
    if not match:
        return None
    index = int(match.group(1)) - 1
    options = pending.get('options') if isinstance(pending.get('options'), list) else []
    if index < 0 or index >= len(options):
        return f'Escolha um número entre 1 e {len(options)}.'

    option = options[index]
    data.pop(key, None)
    _save(data)
    return _execute(option)
