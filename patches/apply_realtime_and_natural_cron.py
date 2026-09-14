#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path.home() / ".hermes" / "core-v2"
CORE = ROOT / "core_entry.py"
WEB = ROOT / "web_router.py"
CRON = ROOT / "cron_manager.py"

CORE_MARKER = "# HERMES_REALTIME_ROUTING_V1"
WEB_MARKER = "# HERMES_REALTIME_WEB_V1"
CRON_MARKER = "# HERMES_NATURAL_CRON_V1"


def insert_before_main(path: Path, marker: str, block: str) -> None:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        print(f"[skip] {path.name}: patch already applied")
        return
    needle = '\nif __name__ == \'__main__\':\n'
    if needle not in text:
        raise RuntimeError(f"main guard not found in {path}")
    text = text.replace(needle, "\n" + block.rstrip() + "\n" + needle, 1)
    path.write_text(text, encoding="utf-8")
    print(f"[ok] {path.name}")


def patch_web() -> None:
    block = r'''
# HERMES_REALTIME_WEB_V1
_REALTIMe_TERMS = (
    'agora', 'hoje', 'neste momento', 'nesse momento', 'atualmente', 'atual', 'atualizado',
    'temperatura', 'clima', 'tempo em', 'vai chover', 'chuva', 'previsao do tempo', 'previsão do tempo',
    'cotacao', 'cotação', 'preco agora', 'preço agora', 'noticias de hoje', 'notícias de hoje',
    'resultado de hoje', 'placar', 'esta aberto agora', 'está aberto agora',
)
_SOURCE_FOLLOWUP_TERMS = (
    'de onde voce pegou', 'de onde você pegou', 'qual a fonte', 'fonte dessa', 'fonte disso',
    'pegou de onde', 'onde conseguiu essa informacao', 'onde conseguiu essa informação',
)


def _needs_fresh_web(text: str) -> bool:
    low = str(text or '').casefold().strip()
    return any(term in low for term in _REALTIMe_TERMS) or any(term in low for term in _SOURCE_FOLLOWUP_TERMS)


def _previous_user_query() -> str:
    try:
        from conversation_memory import recent
        rows = recent(limit=8)
        for row in reversed(rows):
            if row.get('role') != 'user':
                continue
            candidate = str(row.get('text') or '').strip()
            low = candidate.casefold()
            if candidate and not any(term in low for term in _SOURCE_FOLLOWUP_TERMS):
                return candidate
    except Exception:
        pass
    return ''


_handle_before_realtime_patch = handle


def handle(text: str) -> str | None:
    direct = _handle_before_realtime_patch(text)
    if direct is not None:
        return direct

    raw = str(text or '').strip()
    low = raw.casefold()
    if not _needs_fresh_web(raw):
        return None

    query = raw
    if any(term in low for term in _SOURCE_FOLLOWUP_TERMS):
        previous = _previous_user_query()
        if not previous:
            return 'A resposta anterior não tem uma fonte verificável registrada. Não vou inventar uma fonte.'
        query = previous

    try:
        result = research(query, limit=6)
        rendered = format_research(result)
    except Exception as exc:
        return f'Não consegui consultar uma fonte atual agora. Detalhe: {exc}'

    if not rendered or not rendered.strip():
        return 'Não consegui encontrar uma fonte atual confiável para responder isso agora.'
    return rendered
'''
    insert_before_main(WEB, WEB_MARKER, block)


def patch_core() -> None:
    block = r'''
# HERMES_REALTIME_ROUTING_V1
_REALTIME_TERMS = (
    'agora', 'hoje', 'neste momento', 'nesse momento', 'atualmente', 'atual', 'atualizado',
    'temperatura', 'clima', 'tempo em', 'vai chover', 'chuva', 'previsao do tempo', 'previsão do tempo',
    'cotacao', 'cotação', 'preco agora', 'preço agora', 'noticias de hoje', 'notícias de hoje',
    'resultado de hoje', 'placar', 'esta aberto agora', 'está aberto agora',
    'de onde voce pegou', 'de onde você pegou', 'qual a fonte', 'fonte dessa', 'fonte disso',
    'pegou de onde', 'onde conseguiu essa informacao', 'onde conseguiu essa informação',
)


def _requires_fresh_web(text: str) -> bool:
    low = str(text or '').casefold().strip()
    return any(term in low for term in _REALTIME_TERMS)


_ask_before_realtime_patch = ask


def ask(text: str) -> str:
    clean = str(text or '').strip()
    if _requires_fresh_web(clean):
        reply = _web_reply(clean)
        if reply is not None:
            _persist_turn(clean, reply)
            return reply
    return _ask_before_realtime_patch(clean)
'''
    insert_before_main(CORE, CORE_MARKER, block)


def patch_cron() -> None:
    block = r'''
# HERMES_NATURAL_CRON_V1

def _daily_window(text: str) -> tuple[int, int, int] | None:
    t = norm(text)
    match = re.search(
        r'\b(?:das|de)\s*(\d{1,2})(?::(\d{2}))?\s*(?:h|horas?)?\s*'
        r'(?:ate|até|a)\s*(?:as|às)?\s*(\d{1,2})(?::(\d{2}))?\s*(?:h|horas?)?\b',
        t,
    )
    if not match:
        return None
    start_h = max(0, min(23, int(match.group(1))))
    start_m = max(0, min(59, int(match.group(2) or 0)))
    end_h = max(0, min(23, int(match.group(3))))
    end_m = max(0, min(59, int(match.group(4) or 0)))
    if start_m != end_m or end_h < start_h:
        return None
    every = 1
    freq = re.search(r'\ba cada\s+(\d+)\s*(?:hora|horas)\b', t)
    if freq:
        every = max(1, int(freq.group(1)))
    return start_h, end_h, every


def _quantity_goal(text: str) -> tuple[float, str] | None:
    t = norm(text).replace(',', '.')
    m = re.search(r'\b(\d+(?:\.\d+)?)\s*(litros?|l|ml|mililitros?)\b', t)
    if not m:
        return None
    return float(m.group(1)), m.group(2)


def _window_message(text: str, occurrences: int) -> str:
    kind, content = extract_topic(text)
    quantity = _quantity_goal(text)
    if quantity and occurrences > 0:
        amount, unit = quantity
        if unit in {'litro', 'litros', 'l'}:
            each_ml = round((amount * 1000.0) / occurrences)
            return f'{content}. Meta distribuída: aproximadamente {each_ml} ml neste horário.'
        if unit in {'ml', 'mililitro', 'mililitros'}:
            each_ml = round(amount / occurrences)
            return f'{content}. Meta distribuída: aproximadamente {each_ml} ml neste horário.'
    return content


def _create_window_jobs(text: str, window: tuple[int, int, int]) -> str:
    start_h, end_h, every = window
    hours = list(range(start_h, end_h + 1, every))
    if not hours:
        return 'Não consegui montar os horários dessa rotina.'

    kind, base_content = extract_topic(text)
    message = _window_message(text, len(hours))
    created: list[tuple[str, str, str, Path]] = []
    tasks = load_tasks()

    for hour in hours:
        task_id = uuid.uuid4().hex[:12]
        slug = f'managed-{task_id}.sh'
        schedule = f'every day at {hour:02d}:00'
        name = make_name(kind, base_content) + f' {hour:02d}:00'
        tasks[task_id] = {
            'type': kind,
            'message': message if kind in {'reminder', 'agent_task'} else '',
            'query': base_content if kind == 'news' else '',
            'schedule': schedule,
            'name': name,
            'source': 'telegram-natural-language-window',
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
            for old_task_id, _, _, old_script in created:
                tasks.pop(old_task_id, None)
                try:
                    old_script.unlink()
                except Exception:
                    pass
            tasks.pop(task_id, None)
            save_tasks(tasks)
            try:
                script.unlink()
            except Exception:
                pass
            return f'Não consegui criar a rotina completa. {out[-500:]}'
        created.append((task_id, schedule, name, script))

    save_tasks(tasks)
    times = ', '.join(f'{h:02d}:00' for h in hours)
    quantity = _quantity_goal(text)
    distribution = ''
    if quantity:
        amount, unit = quantity
        total_ml = amount * 1000.0 if unit in {'litro', 'litros', 'l'} else amount
        distribution = f'\nDistribuição aproximada: {round(total_ml / len(hours))} ml por lembrete'
    return (
        f'✅ Rotina criada com {len(hours)} lembretes diários\n'
        f'Horários: {times}{distribution}\nEntrega: Telegram'
    )


_create_job_before_natural_window_patch = create_job


def create_job(text: str) -> str:
    window = _daily_window(text)
    if window is not None:
        return _create_window_jobs(text, window)
    return _create_job_before_natural_window_patch(text)
'''
    insert_before_main(CRON, CRON_MARKER, block)


def main() -> int:
    for required in (CORE, WEB, CRON):
        if not required.exists():
            raise SystemExit(f"missing runtime file: {required}")
    patch_web()
    patch_core()
    patch_cron()
    print("OK: realtime/current-info routing + natural daily-window reminders applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
