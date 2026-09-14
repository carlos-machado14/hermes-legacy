#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path.home() / ".hermes" / "core-v2"
CRON = ROOT / "cron_manager.py"
FASTPATH = Path.home() / ".hermes" / "plugins" / "hermes-core-fastpath" / "__init__.py"

CRON_MARKER = "# HERMES_ROUTINE_CONFIRMATION_V1"
FASTPATH_MARKER = "# HERMES_PENDING_ROUTINE_ROUTING_V1"


def insert_before_main(path: Path, marker: str, block: str) -> None:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        print(f"[skip] {path}: already patched")
        return
    needle = "\nif __name__ == '__main__':\n"
    rendered = "\n" + block.rstrip() + "\n"
    if needle in text:
        text = text.replace(needle, rendered + needle, 1)
    else:
        text = text.rstrip() + rendered + "\n"
    path.write_text(text, encoding="utf-8")
    print(f"[ok] {path}")


def patch_cron() -> None:
    block = r'''
# HERMES_ROUTINE_CONFIRMATION_V1
PENDING_ROUTINES_FILE = STATE / 'pending_routines.json'


def _load_pending_routines() -> dict:
    try:
        data = json.loads(PENDING_ROUTINES_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_pending_routines(data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    PENDING_ROUTINES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _pending_get(chat_key: str) -> dict | None:
    return _load_pending_routines().get(chat_key or 'default')


def _pending_set(chat_key: str, draft: dict) -> None:
    data = _load_pending_routines()
    data[chat_key or 'default'] = draft
    _save_pending_routines(data)


def _pending_clear(chat_key: str) -> None:
    data = _load_pending_routines()
    data.pop(chat_key or 'default', None)
    _save_pending_routines(data)


def _frequency_minutes(text: str) -> int | None:
    t = norm(text)
    patterns = (
        r'\ba cada\s+(\d+)\s*(?:minuto|minutos|min)\b',
        r'\b(?:de|em)\s+(\d+)\s*(?:em\s+\d+\s*)?(?:minuto|minutos|min)\b',
        r'^\s*(\d+)\s*(?:minuto|minutos|min)\s*$',
    )
    for pattern in patterns:
        m = re.search(pattern, t)
        if m:
            value = int(m.group(1))
            return value if value > 0 else None
    hours = re.search(r'\ba cada\s+(\d+)\s*(?:hora|horas)\b', t)
    if hours:
        value = int(hours.group(1)) * 60
        return value if value > 0 else None
    return None


def _window_minutes(text: str) -> tuple[int, int] | None:
    t = norm(text)
    m = re.search(
        r'\b(?:das|de)\s*(\d{1,2})(?::(\d{2}))?\s*(?:h|horas?)?\s*'
        r'(?:ate|até|a)\s*(?:as|às)?\s*(\d{1,2})(?::(\d{2}))?\s*(?:h|horas?)?\b',
        t,
    )
    if not m:
        return None
    sh = max(0, min(23, int(m.group(1))))
    sm = max(0, min(59, int(m.group(2) or 0)))
    eh = max(0, min(23, int(m.group(3))))
    em = max(0, min(59, int(m.group(4) or 0)))
    start = sh * 60 + sm
    end = eh * 60 + em
    return (start, end) if end >= start else None


def _format_clock(total_minutes: int) -> str:
    return f'{total_minutes // 60:02d}:{total_minutes % 60:02d}'


def _goal_total_ml(text: str) -> int | None:
    parsed = _quantity_goal(text) if '_quantity_goal' in globals() else None
    if not parsed:
        t = norm(text).replace(',', '.')
        m = re.search(r'\b(\d+(?:\.\d+)?)\s*(litros?|l|ml|mililitros?)\b', t)
        if not m:
            return None
        parsed = (float(m.group(1)), m.group(2))
    amount, unit = parsed
    return round(amount * 1000) if unit in {'litro', 'litros', 'l'} else round(amount)


def _confirmation_words(text: str) -> bool:
    t = norm(text)
    return t in {
        'sim', 'sim pode', 'sim pode criar', 'pode criar', 'pode fazer', 'confirmo',
        'confirmado', 'esta correto', 'está correto', 'correto', 'ok', 'fechado', 'manda ver',
    }


def _cancel_words(text: str) -> bool:
    t = norm(text)
    return t in {'nao', 'não', 'cancela', 'cancelar', 'deixa', 'deixa pra la', 'deixa pra lá', 'esquece'}


def _summary_window(draft: dict) -> str:
    start = int(draft['start'])
    end = int(draft['end'])
    freq = int(draft['frequency_minutes'])
    times = list(range(start, end + 1, freq))
    lines = [
        'Antes de criar, confirma se entendi corretamente:',
        f"• Rotina: {draft.get('topic') or 'lembrete'}",
        f"• Período: {_format_clock(start)} até {_format_clock(end)}",
        f"• Frequência: a cada {freq} minutos",
        f"• Lembretes por dia: {len(times)}",
    ]
    total_ml = draft.get('total_ml')
    if total_ml:
        each = round(int(total_ml) / max(1, len(times)))
        lines.append(f"• Meta diária: {int(total_ml)} ml")
        lines.append(f"• Aproximadamente {each} ml por lembrete")
    lines.append('Está correto? Responda “sim” para eu criar, ou diga o que quer alterar.')
    return '\n'.join(lines)


def _summary_generic(draft: dict) -> str:
    schedule = parse_schedule(draft.get('text') or '')
    return (
        'Antes de criar, confirma se entendi corretamente:\n'
        f"• Rotina: {draft.get('topic') or draft.get('text')}\n"
        f"• Agenda: {schedule or 'a definir'}\n"
        'Está correto? Responda “sim” para eu criar, ou diga o que quer alterar.'
    )


def _make_window_draft(text: str) -> dict | None:
    window = _window_minutes(text)
    if not window:
        return None
    kind, topic = extract_topic(text)
    freq = _frequency_minutes(text)
    return {
        'type': 'window',
        'text': text,
        'kind': kind,
        'topic': topic,
        'start': window[0],
        'end': window[1],
        'frequency_minutes': freq,
        'total_ml': _goal_total_ml(text),
        'stage': 'confirm' if freq else 'frequency',
    }


def _create_confirmed_window(draft: dict) -> str:
    start = int(draft['start'])
    end = int(draft['end'])
    freq = int(draft['frequency_minutes'])
    if freq <= 0:
        return 'A frequência precisa ser maior que zero.'
    times = list(range(start, end + 1, freq))
    if not times:
        return 'Não consegui montar os horários dessa rotina.'
    if len(times) > 96:
        return 'Essa configuração criaria mais de 96 lembretes por dia. Escolha um intervalo maior.'

    kind = str(draft.get('kind') or 'reminder')
    topic = str(draft.get('topic') or draft.get('text') or 'lembrete')
    total_ml = draft.get('total_ml')
    per_reminder = round(int(total_ml) / len(times)) if total_ml else None
    message = topic
    if per_reminder:
        message = f'{topic}. Meta deste lembrete: aproximadamente {per_reminder} ml.'

    tasks = load_tasks()
    created_job_ids: list[str] = []
    created_task_ids: list[str] = []
    created_scripts: list[Path] = []

    for minute_of_day in times:
        task_id = uuid.uuid4().hex[:12]
        slug = f'managed-{task_id}.sh'
        clock = _format_clock(minute_of_day)
        schedule = f'every day at {clock}'
        name = make_name(kind, topic) + f' {clock}'
        tasks[task_id] = {
            'type': kind,
            'message': message if kind in {'reminder', 'agent_task'} else '',
            'query': topic if kind == 'news' else '',
            'schedule': schedule,
            'name': name,
            'source': 'telegram-confirmed-natural-language-window',
        }
        SCRIPTS.mkdir(parents=True, exist_ok=True)
        script = SCRIPTS / slug
        script.write_text(
            '#!/usr/bin/env bash\nset -euo pipefail\n' + f'exec "{PYTHON}" "{RUNNER}" "{task_id}"\n',
            encoding='utf-8',
        )
        script.chmod(0o700)
        save_tasks(tasks)
        code, out = run([
            HERMES, 'cron', 'create', schedule, '--no-agent', '--script', slug,
            '--deliver', 'telegram', '--name', name,
        ])
        if code != 0:
            for job_id in created_job_ids:
                run([HERMES, 'cron', 'remove', job_id])
            for old_task_id in created_task_ids:
                tasks.pop(old_task_id, None)
            tasks.pop(task_id, None)
            for old_script in created_scripts + [script]:
                try:
                    old_script.unlink()
                except Exception:
                    pass
            save_tasks(tasks)
            return f'Não consegui criar a rotina completa. {out[-500:]}'
        match = re.search(r'Created job:\s*([^\s]+)', out)
        if match:
            created_job_ids.append(match.group(1))
        created_task_ids.append(task_id)
        created_scripts.append(script)

    save_tasks(tasks)
    clocks = ', '.join(_format_clock(value) for value in times)
    detail = f'\nAproximadamente {per_reminder} ml por lembrete.' if per_reminder else ''
    return (
        f'✅ Rotina criada após sua confirmação.\n'
        f'Frequência: a cada {freq} minutos\n'
        f'Período: {_format_clock(start)} até {_format_clock(end)}\n'
        f'Total: {len(times)} lembretes por dia{detail}\n'
        f'Horários: {clocks}'
    )


_create_job_before_confirmation_patch = create_job
_handle_before_confirmation_patch = handle


def _start_routine_draft(text: str, chat_key: str) -> str:
    draft = _make_window_draft(text)
    if draft is not None:
        _pending_set(chat_key, draft)
        if not draft.get('frequency_minutes'):
            return (
                'Entendi a rotina e não vou criar nada sem você confirmar.\n'
                f"Período: {_format_clock(int(draft['start']))} até {_format_clock(int(draft['end']))}.\n"
                'De quanto em quanto tempo você quer o lembrete? Ex.: a cada 10, 15, 20 ou 30 minutos.'
            )
        return _summary_window(draft)

    schedule = parse_schedule(text)
    kind, topic = extract_topic(text)
    draft = {
        'type': 'generic',
        'text': text,
        'kind': kind,
        'topic': topic,
        'stage': 'confirm' if schedule else 'schedule',
    }
    _pending_set(chat_key, draft)
    if not schedule:
        return (
            'Entendi que você quer criar uma rotina, mas não vou criar sem alinharmos antes.\n'
            'Qual horário ou frequência você quer? Ex.: “todo dia às 8h” ou “a cada 30 minutos”.'
        )
    return _summary_generic(draft)


def _continue_routine_draft(text: str, chat_key: str, draft: dict) -> str:
    if _cancel_words(text):
        _pending_clear(chat_key)
        return 'Certo. Não criei a rotina e descartei essa configuração.'

    if draft.get('type') == 'window':
        frequency = _frequency_minutes(text)
        if frequency is not None:
            draft['frequency_minutes'] = frequency
            draft['stage'] = 'confirm'
            _pending_set(chat_key, draft)
            return _summary_window(draft)
        if _confirmation_words(text):
            if not draft.get('frequency_minutes'):
                return 'Antes de confirmar, me diga de quanto em quanto tempo você quer o lembrete.'
            result = _create_confirmed_window(draft)
            if result.startswith('✅'):
                _pending_clear(chat_key)
            return result
        return (
            'Ainda não alterei nem criei nada. Diga a frequência desejada, por exemplo “a cada 15 minutos”, '
            'ou responda “não” para cancelar.'
        )

    combined = f"{draft.get('text', '')} {text}".strip()
    if draft.get('stage') == 'schedule':
        if parse_schedule(combined) is not None:
            draft['text'] = combined
            draft['stage'] = 'confirm'
            _pending_set(chat_key, draft)
            return _summary_generic(draft)
        return 'Ainda falta o horário/frequência. Ex.: “todo dia às 8h” ou “a cada 30 minutos”.'

    if _confirmation_words(text):
        result = _create_job_before_confirmation_patch(draft.get('text') or '')
        if result.startswith('✅'):
            _pending_clear(chat_key)
        return result

    if parse_schedule(combined) is not None:
        draft['text'] = combined
        _pending_set(chat_key, draft)
        return _summary_generic(draft)

    return 'Não criei nada ainda. Responda “sim” para confirmar ou diga o que quer alterar.'


def handle(text: str, chat_key: str = 'default') -> str:
    pending = _pending_get(chat_key)
    if pending is not None:
        return _continue_routine_draft(text, chat_key, pending)
    if _creation_intent(text):
        return _start_routine_draft(text, chat_key)
    return _handle_before_confirmation_patch(text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--text-b64', required=True)
    parser.add_argument('--chat-key', default='default')
    args = parser.parse_args()
    try:
        text = base64.urlsafe_b64decode(args.text_b64.encode()).decode('utf-8')
    except Exception:
        print(RESULT_PREFIX + 'Não consegui interpretar a solicitação.')
        return 2
    print(RESULT_PREFIX + handle(text, chat_key=args.chat_key))
    return 0
'''
    insert_before_main(CRON, CRON_MARKER, block)


def patch_fastpath() -> None:
    text = FASTPATH.read_text(encoding='utf-8')
    changed = False

    if FASTPATH_MARKER not in text:
        anchor = "\ndef pre_gateway_dispatch(event: Any = None, **kwargs):\n"
        helper = r'''

# HERMES_PENDING_ROUTINE_ROUTING_V1
_PENDING_ROUTINE_REPLY_RE = re.compile(
    r'^(?:\s*(?:sim|não|nao|ok|confirmo|confirmado|correto|pode criar|pode fazer|cancela|cancelar|esquece)\s*[.!]?\s*$|'
    r'.*\b(?:a cada\s+\d+\s*(?:minutos?|horas?)|\d+\s*(?:minutos?|horas?)|todo dia|todos os dias|diariamente|às?\s*\d{1,2})\b.*)',
    re.IGNORECASE,
)


def _pending_cron_exists(key: str) -> bool:
    try:
        path = Path.home() / '.hermes' / 'core-v2' / 'state' / 'pending_routines.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        return isinstance(data, dict) and key in data
    except Exception:
        return False
'''
        if anchor not in text:
            raise RuntimeError('pre_gateway_dispatch anchor not found')
        text = text.replace(anchor, helper + anchor, 1)
        changed = True

    old_call = "[str(py), str(manager), '--text-b64', encoded],"
    new_call = "[str(py), str(manager), '--text-b64', encoded, '--chat-key', key],"
    if old_call in text:
        text = text.replace(old_call, new_call, 1)
        changed = True

    old_route = "    _ensure_worker()\n    is_cron = bool(CRON_RE.search(text))\n    tier = _classify_complexity(text, is_cron=is_cron)\n    key = _chat_key(source)\n"
    new_route = "    _ensure_worker()\n    key = _chat_key(source)\n    is_cron = bool(CRON_RE.search(text)) or (_pending_cron_exists(key) and bool(_PENDING_ROUTINE_REPLY_RE.search(text)))\n    tier = _classify_complexity(text, is_cron=is_cron)\n"
    if old_route in text:
        text = text.replace(old_route, new_route, 1)
        changed = True

    if changed:
        FASTPATH.write_text(text, encoding='utf-8')
        print(f'[ok] {FASTPATH}')
    else:
        print(f'[skip] {FASTPATH}: no changes needed')


def main() -> int:
    for path in (CRON, FASTPATH):
        if not path.exists():
            raise SystemExit(f'missing runtime file: {path}')
    patch_cron()
    patch_fastpath()
    print('OK: routines now require conversational setup + explicit confirmation before creation')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
