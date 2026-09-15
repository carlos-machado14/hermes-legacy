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
CHANNEL_FILE = STATE / 'channel_state.json'
TTL_SECONDS = 15 * 60
APPROVAL_TTL_SECONDS = 24 * 3600
APPROVAL_REMIND_SECONDS = 12 * 3600


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


def _channel_key() -> str:
    try:
        row = json.loads(CHANNEL_FILE.read_text(encoding='utf-8'))
        if isinstance(row, dict):
            platform = str(row.get('platform') or 'telegram').strip().lower()
            chat_id = str(row.get('chat_id') or row.get('user_id') or '').strip()
            if chat_id:
                return f'{platform}:{chat_id}'
    except Exception:
        pass
    return 'telegram:default'


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
    if not isinstance(pending, dict) or pending.get('type') == 'approval':
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


def _approval_storage_key(*, from_channel: bool = False) -> str:
    source = _channel_key() if from_channel else _source_key()
    return f'approval::{source}'


def _approval_live(ids: list[str]) -> list[dict[str, Any]]:
    from action_queue import get_action
    rows = []
    for ref in ids:
        action = get_action(ref)
        if action and action.get('status') == 'pending_approval':
            rows.append(action)
    return rows


def _approval_detail(action: dict[str, Any], index: int | None = None) -> str:
    prefix = f'{index}. ' if index is not None else ''
    return (
        f"{prefix}{action.get('title')}\n"
        f"   ID: {action.get('id')} | tipo: {action.get('kind') or 'ação'} | risco: {action.get('risk') or 'desconhecido'}"
    )


def _approval_root(actions: list[dict[str, Any]]) -> str:
    if len(actions) == 1:
        return (
            '🤖 Hermes — preciso da sua decisão\n\n'
            + _approval_detail(actions[0])
            + '\n\n1. Aprovar\n2. Recusar\n3. Ver detalhes\n4. Decidir depois\n\n'
            + 'Responda apenas com o número.'
        )
    lines = ['🤖 Hermes — preciso da sua decisão', '', 'Há ações aguardando aprovação:']
    for action in actions:
        lines.append(f"- {action.get('title')} [{action.get('id')}]")
    lines += [
        '', 'O que deseja fazer?',
        '1. Aprovar todas',
        '2. Recusar todas',
        '3. Revisar uma por uma',
        '4. Ver detalhes de todas',
        '5. Decidir depois',
        '', 'Responda apenas com o número.',
    ]
    return '\n'.join(lines)


def register_approval_prompt(actions: list[dict[str, Any]]) -> str | None:
    pending = [a for a in actions if a.get('status') == 'pending_approval']
    ids = list(dict.fromkeys(str(a.get('id')) for a in pending if a.get('id')))
    if not ids:
        return None
    data = _load()
    key = _approval_storage_key(from_channel=True)
    now = int(time.time())
    existing = data.get(key) if isinstance(data.get(key), dict) else None
    if existing:
        previous = [str(x) for x in existing.get('action_ids') or []]
        if previous == ids and now - int(existing.get('notified_at') or 0) < APPROVAL_REMIND_SECONDS:
            return None
    data[key] = {
        'type': 'approval',
        'action_ids': ids,
        'mode': 'root',
        'selected_id': None,
        'created_at': now,
        'notified_at': now,
        'expires_at': now + APPROVAL_TTL_SECONDS,
    }
    _save(data)
    return _approval_root(pending)


def _approval_refresh(data: dict[str, Any], key: str, row: dict[str, Any]) -> list[dict[str, Any]]:
    live = _approval_live([str(x) for x in row.get('action_ids') or []])
    if live:
        row['action_ids'] = [str(x.get('id')) for x in live]
        row['expires_at'] = int(time.time()) + APPROVAL_TTL_SECONDS
        data[key] = row
    else:
        data.pop(key, None)
    _save(data)
    return live


def _approval_apply(action: dict[str, Any], approve_it: bool) -> str:
    if approve_it:
        from goal_execution_engine import approve_and_execute
        updated = approve_and_execute(str(action['id']))
        result = str(updated.get('result') or '').strip()
        return f"✅ Aprovado: {action.get('title')}" + (f'\n{result}' if result else '')
    from action_queue import reject
    reject(str(action['id']))
    return f"❌ Recusado: {action.get('title')}"


def _approval_details(actions: list[dict[str, Any]]) -> str:
    lines = ['🔎 Detalhes das ações aguardando aprovação:']
    for index, action in enumerate(actions, 1):
        lines += ['', _approval_detail(action, index)]
    return '\n'.join(lines)


def _approval_pick(actions: list[dict[str, Any]]) -> str:
    lines = ['Qual ação você quer revisar?']
    for index, action in enumerate(actions, 1):
        lines.append(f"{index}. {action.get('title')} [{action.get('id')}]")
    lines += ['0. Voltar', '', 'Responda apenas com o número.']
    return '\n'.join(lines)


def _approval_action_menu(action: dict[str, Any]) -> str:
    return (
        f"Você escolheu:\n{action.get('title')} [{action.get('id')}]\n\n"
        '1. Aprovar\n2. Recusar\n3. Ver detalhes\n4. Voltar\n\n'
        'Responda apenas com o número.'
    )


def resolve_approval_pending(text: str) -> str | None:
    data = _load()
    key = _approval_storage_key()
    row = data.get(key)
    if not isinstance(row, dict):
        approval_keys = [k for k, value in data.items() if k.startswith('approval::') and isinstance(value, dict)]
        if len(approval_keys) == 1:
            key = approval_keys[0]
            row = data[key]
        else:
            return None

    actions = _approval_refresh(data, key, row)
    if not actions:
        return None
    row = data.get(key)
    if not isinstance(row, dict):
        return None

    low = _norm(text)
    direct = re.fullmatch(r'(aprovar|aprove|rejeitar|recusar|recuse)\s+([0-9a-f]{4,16})', low)
    if direct:
        ref = direct.group(2)
        action = next((a for a in actions if str(a.get('id') or '').startswith(ref)), None)
        if not action:
            return 'Não encontrei essa ação entre as aprovações pendentes.'
        reply = _approval_apply(action, direct.group(1).startswith(('aprov', 'aprove')))
        remaining = _approval_refresh(data, key, row)
        if remaining:
            reply += f'\n\nAinda há {len(remaining)} ação(ões) aguardando sua decisão.'
        return reply

    if low in {'depois', 'deixa para depois', 'deixe para depois'}:
        row['mode'] = 'deferred'; row['notified_at'] = int(time.time()); data[key] = row; _save(data)
        return 'Certo. Não executei nada. Essas ações continuam aguardando sua aprovação.'

    match = re.fullmatch(r'(?:opcao\s*)?(\d+)', low)
    if not match:
        return None
    choice = int(match.group(1))
    mode = str(row.get('mode') or 'root')

    if mode == 'deferred':
        row['mode'] = 'root'; data[key] = row; _save(data)
        return _approval_root(actions)

    if mode == 'root':
        if len(actions) == 1:
            action = actions[0]
            if choice == 1:
                reply = _approval_apply(action, True); _approval_refresh(data, key, row); return reply
            if choice == 2:
                reply = _approval_apply(action, False); _approval_refresh(data, key, row); return reply
            if choice == 3:
                return _approval_details(actions) + '\n\n' + _approval_action_menu(action)
            if choice == 4:
                row['mode'] = 'deferred'; row['notified_at'] = int(time.time()); data[key] = row; _save(data)
                return 'Certo. Não executei nada. Posso lembrar novamente mais tarde.'
            return 'Escolha 1, 2, 3 ou 4.'

        if choice == 1:
            replies = [_approval_apply(action, True) for action in actions]
            _approval_refresh(data, key, row)
            return '\n'.join(replies)
        if choice == 2:
            replies = [_approval_apply(action, False) for action in actions]
            _approval_refresh(data, key, row)
            return '\n'.join(replies)
        if choice == 3:
            row['mode'] = 'pick'; data[key] = row; _save(data)
            return _approval_pick(actions)
        if choice == 4:
            return _approval_details(actions) + '\n\n' + _approval_root(actions)
        if choice == 5:
            row['mode'] = 'deferred'; row['notified_at'] = int(time.time()); data[key] = row; _save(data)
            return 'Certo. Não executei nada. Essas ações continuam aguardando sua aprovação.'
        return 'Escolha um número entre 1 e 5.'

    if mode == 'pick':
        if choice == 0:
            row['mode'] = 'root'; row['selected_id'] = None; data[key] = row; _save(data)
            return _approval_root(actions)
        if choice < 1 or choice > len(actions):
            return f'Escolha um número entre 1 e {len(actions)}, ou 0 para voltar.'
        action = actions[choice - 1]
        row['mode'] = 'action'; row['selected_id'] = str(action['id']); data[key] = row; _save(data)
        return _approval_action_menu(action)

    if mode == 'action':
        selected = str(row.get('selected_id') or '')
        action = next((a for a in actions if str(a.get('id') or '') == selected), None)
        if not action:
            row['mode'] = 'pick'; row['selected_id'] = None; data[key] = row; _save(data)
            return _approval_pick(actions)
        if choice in {1, 2}:
            reply = _approval_apply(action, choice == 1)
            remaining = _approval_refresh(data, key, row)
            if remaining:
                current = data.get(key) or row
                current['mode'] = 'pick'; current['selected_id'] = None; data[key] = current; _save(data)
                reply += '\n\n' + _approval_pick(remaining)
            return reply
        if choice == 3:
            return _approval_details([action]) + '\n\n' + _approval_action_menu(action)
        if choice == 4:
            row['mode'] = 'pick'; row['selected_id'] = None; data[key] = row; _save(data)
            return _approval_pick(actions)
        return 'Escolha 1, 2, 3 ou 4.'

    row['mode'] = 'root'; data[key] = row; _save(data)
    return _approval_root(actions)
