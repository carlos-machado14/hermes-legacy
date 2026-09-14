#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

CRON = Path.home() / '.hermes' / 'core-v2' / 'cron_manager.py'
MARKER = '# HERMES_ROUTINE_MUTATION_CONFIRMATION_V2'

BLOCK = r'''
# HERMES_ROUTINE_MUTATION_CONFIRMATION_V2
PENDING_ROUTINE_OPS_FILE = STATE / 'pending_routine_operations.json'


def _load_pending_ops() -> dict:
    try:
        data = json.loads(PENDING_ROUTINE_OPS_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_pending_ops(data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    PENDING_ROUTINE_OPS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _op_words(text: str) -> tuple[str, str] | None:
    t = norm(text)
    mapping = [
        (("pause", "pausar", "pare", "parar"), "pause"),
        (("retome", "retomar", "continuar", "resume"), "resume"),
        (("remova", "remover", "apague", "apagar", "exclua", "excluir", "delete"), "remove"),
        (("rode", "rodar", "execute", "executar"), "run"),
    ]
    for words, command in mapping:
        for word in words:
            if t.startswith(word + ' '):
                target = extract_target(text, r'(?:' + '|'.join(words) + r')')
                return command, target
    return None


def _op_label(command: str) -> str:
    return {'pause': 'pausar', 'resume': 'retomar', 'remove': 'remover', 'run': 'executar agora'}.get(command, command)


def _op_confirm(text: str) -> bool:
    return _confirmation_words(text) if '_confirmation_words' in globals() else norm(text) in {'sim','confirmo','pode fazer','pode executar','ok'}


def _op_cancel(text: str) -> bool:
    return _cancel_words(text) if '_cancel_words' in globals() else norm(text) in {'nao','não','cancela','cancelar'}


_handle_before_mutation_confirmation_v2 = handle


def handle(text: str, chat_key: str = 'default') -> str:
    key = chat_key or 'default'
    pending_all = _load_pending_ops()
    pending = pending_all.get(key)
    if isinstance(pending, dict):
        if _op_cancel(text):
            pending_all.pop(key, None)
            _save_pending_ops(pending_all)
            return 'Certo. Não alterei nenhuma rotina.'
        if _op_confirm(text):
            command = str(pending.get('command') or '')
            target = str(pending.get('target') or '').strip()
            code, out = run([HERMES, 'cron', command, target])
            if code != 0:
                return f"Não consegui {_op_label(command)} a rotina '{target}'. {out[-500:]}"
            pending_all.pop(key, None)
            _save_pending_ops(pending_all)
            labels = {'pause': 'pausada', 'resume': 'retomada', 'remove': 'removida', 'run': 'executada'}
            return f"✅ Rotina {labels.get(command, command)} após sua confirmação: {target}"
        operation = _op_words(text)
        if operation and operation[1]:
            command, target = operation
            pending = {'command': command, 'target': target, 'requested_at': datetime.now().astimezone().isoformat()}
            pending_all[key] = pending
            _save_pending_ops(pending_all)
        return (
            f"Ainda não executei nada. Vou {_op_label(str(pending.get('command')))} a rotina "
            f"'{pending.get('target')}'. Está correto? Responda “sim” para confirmar ou “não” para cancelar."
        )

    operation = _op_words(text)
    if operation:
        command, target = operation
        if not target:
            return f"Entendi que você quer {_op_label(command)} uma rotina. Qual é o nome ou ID dela?"
        pending_all[key] = {
            'command': command,
            'target': target,
            'requested_at': datetime.now().astimezone().isoformat(),
        }
        _save_pending_ops(pending_all)
        return (
            f"Antes de executar: vou {_op_label(command)} a rotina '{target}'. "
            'Está correto? Responda “sim” para confirmar ou diga o que quer alterar.'
        )

    return _handle_before_mutation_confirmation_v2(text, chat_key=chat_key)
'''


def main() -> int:
    text = CRON.read_text(encoding='utf-8')
    if MARKER in text:
        print('[skip] routine mutation confirmation already active')
        return 0
    needle = "\nif __name__ == '__main__':\n"
    if needle in text:
        text = text.replace(needle, '\n' + BLOCK.rstrip() + '\n' + needle, 1)
    else:
        text = text.rstrip() + '\n\n' + BLOCK.rstrip() + '\n'
    CRON.write_text(text, encoding='utf-8')
    print('OK: pause/resume/run/remove now require explicit confirmation')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
