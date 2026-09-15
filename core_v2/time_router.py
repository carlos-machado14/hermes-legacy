from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Any

from temporal_parser import extract_alert_offsets, humanize, norm, parse
from time_store import DEFAULT_TZ, compute_next, create_schedule, get_schedule, latest_schedule, list_schedules, pause, remove, resume, snooze, tz, update_schedule


def _looks_temporal(text: str) -> bool:
    t = norm(text)
    hints = (
        'lembre', 'lembrete', 'agenda', 'agende', 'evento', 'reuniao', 'compromisso', 'cronograma',
        'todo dia', 'todos os dias', 'todo ano', 'cada ', 'a cada ', 'amanha', 'hoje', 'sexta', 'segunda',
        'terca', 'quarta', 'quinta', 'sabado', 'domingo', 'preciso ', 'tenho que', 'tenho ', 'devo ',
    )
    return any(x in t for x in hints)


def _creation_intent(text: str) -> bool:
    t = norm(text)
    if any(x in t for x in ('o que tenho', 'minha agenda', 'meu cronograma', 'agenda de hoje', 'agenda de amanha', 'listar lembretes', 'meus lembretes', 'quais lembretes')):
        return False
    explicit = ('me lembre', 'lembre-me', 'agende', 'agenda ', 'crie um lembrete', 'crie uma rotina', 'tenho reuniao', 'tenho reunião', 'tenho compromisso')
    if any(x in t for x in explicit):
        return True
    if any(x in t for x in ('preciso ', 'tenho que ', 'devo ')) and parse(text) is not None:
        return True
    return parse(text) is not None and any(x in t for x in ('todo ', 'cada ', 'a cada ', 'amanha', 'hoje', 'dia '))


def _kind(text: str) -> str:
    t = norm(text)
    if any(x in t for x in ('reuniao', 'evento', 'compromisso', 'consulta', 'viagem')):
        return 'event'
    if any(x in t for x in ('a cada ', 'todo dia', 'todos os dias', 'rotina', 'habito', 'hábito')):
        return 'routine'
    if any(x in t for x in ('preciso ', 'tenho que ', 'devo ', 'entregar', 'prazo')):
        return 'commitment'
    return 'reminder'


def _message(text: str) -> str:
    raw = str(text or '').strip()
    patterns = [
        r'^.*?me lembre(?:-me)?(?:\s+de)?\s+',
        r'^.*?lembre-me(?:\s+de)?\s+',
        r'^.*?agende\s+',
        r'^.*?crie\s+(?:um|uma)\s+(?:lembrete|rotina|evento)\s+(?:para\s+)?',
    ]
    cleaned = raw
    for pattern in patterns:
        candidate = re.sub(pattern, '', cleaned, count=1, flags=re.I)
        if candidate != cleaned:
            cleaned = candidate
            break

    # When the time expression comes immediately after "me lembre", remove it
    # from the human message. Example: "daqui a 2 minutos de testar o Hermes"
    # must become simply "testar o Hermes".
    leading_temporal = [
        r'^(?:daqui\s+a|em)\s+\d+\s+(?:minutos?|horas?|dias?)\s+(?:de\s+)?',
        r'^(?:hoje|amanhã|amanha)(?:\s+(?:às?|as)\s+\d{1,2}(?::\d{2})?\s*(?:h|horas?)?)?\s+(?:de\s+)?',
        r'^todo\s+dia\s+(?:às?\s+|as\s+)?\d{1,2}(?::\d{2})?\s*(?:h|horas?)?\s+(?:de\s+)?',
        r'^todo\s+dia\s+\d{1,2}\s+(?:do|da|de)?\s*',
        r'^todo\s+ano\s+dia\s+\d{1,2}(?:\s+de\s+[A-Za-zÀ-ÿ]+)?\s+(?:do|da|de)?\s*',
    ]
    for pattern in leading_temporal:
        candidate = re.sub(pattern, '', cleaned, count=1, flags=re.I)
        if candidate != cleaned:
            cleaned = candidate
            break

    cleaned = re.sub(r'\s+a cada\s+\d+\s+(?:minutos?|horas?|dias?).*$', '', cleaned, flags=re.I)
    cleaned = re.sub(r'\s+todo\s+dia\s+\d+.*$', '', cleaned, flags=re.I)
    cleaned = re.sub(r'\s+todo\s+ano\s+.*$', '', cleaned, flags=re.I)
    return cleaned.strip(' .,-') or raw


def _title(message: str, kind: str) -> str:
    prefix = {'event': 'Evento', 'routine': 'Rotina', 'commitment': 'Compromisso', 'reminder': 'Lembrete'}.get(kind, 'Agenda')
    compact = re.sub(r'\s+', ' ', message).strip()
    return f'{prefix} - {compact[:70]}'


def create_from_text(text: str) -> str:
    parsed = parse(text)
    if not parsed:
        return 'Entendi que você quer agendar algo, mas faltou uma data, horário ou frequência.'
    if parsed.get('needs_clarification'):
        return str(parsed['needs_clarification'])
    recurrence = parsed['recurrence']
    kind = _kind(text)
    message = _message(text)
    conflict = ''
    if recurrence.get('freq') == 'once' and parsed.get('next_run_at'):
        target_ts = int(parsed['next_run_at'])
        for existing in list_schedules(status='active', kinds=['event','commitment'], limit=100):
            existing_ts = existing.get('next_run_at')
            if existing_ts and abs(int(existing_ts) - target_ts) < 3600:
                conflict = f"\n⚠️ Conflito possível com: {existing.get('message')}"
                break
    item = create_schedule(_title(message, kind), message, recurrence, kind=kind, timezone=parsed.get('timezone') or DEFAULT_TZ)

    if kind == 'commitment':
        try:
            from task_manager import create_task
            due = datetime.fromtimestamp(int(item['next_run_at']), tz(item['timezone'])).isoformat() if item.get('next_run_at') else None
            create_task(message, priority='medium', due=due, kind='commitment', metadata={'source':'natural-language','schedule_id':item['id']})
        except Exception:
            pass

    if recurrence.get('freq') == 'once':
        try:
            base = datetime.fromisoformat(str(recurrence['at']))
            for minutes in extract_alert_offsets(text):
                at = base - timedelta(minutes=minutes)
                if at.timestamp() > time.time():
                    create_schedule(
                        f'Alerta - {message[:70]}',
                        f'Em {minutes} minuto(s): {message}',
                        {'freq': 'once', 'at': at.isoformat()},
                        kind='alert', timezone=item['timezone'], parent_id=item['id'],
                        metadata={'offset_minutes': minutes},
                    )
        except Exception:
            pass

    next_dt = datetime.fromtimestamp(int(item['next_run_at']), tz(item['timezone'])) if item.get('next_run_at') else None
    next_text = next_dt.strftime('%d/%m/%Y %H:%M') if next_dt else 'sem próxima execução'
    return (
        f"✅ Salvei no Hermes\n"
        f"{message}\n"
        f"Agenda: {humanize(recurrence)}\n"
        f"Timezone: {item['timezone']}\n"
        f"Próximo aviso: {next_text}\n"
        f"ID: {item['id']}" + conflict
    )


def _resolve_target(text: str) -> str | None:
    t = str(text or '').strip()
    m = re.search(r'\b([0-9a-f]{6,16})\b', t, re.I)
    if m:
        return m.group(1)
    m = re.search(r'(?:lembrete|rotina|evento|compromisso)\s+["\']?(.+?)["\']?$', t, re.I)
    if m:
        candidate = m.group(1).strip(" .'\"")
        for item in list_schedules(status='active', limit=100):
            if candidate.casefold() in str(item.get('title') or '').casefold() or candidate.casefold() in str(item.get('message') or '').casefold():
                return str(item['id'])
    if any(x in norm(text) for x in ('isso', 'disso', 'esse lembrete', 'essa rotina')):
        latest = latest_schedule()
        return str(latest['id']) if latest else None
    return None


def _preview(item: dict[str, Any], start: datetime, end: datetime, max_occ: int = 30) -> list[datetime]:
    recurrence = item.get('recurrence') or {}
    zone = tz(item.get('timezone'))
    cursor = int(start.astimezone(zone).timestamp()) - 1
    out: list[datetime] = []
    for _ in range(max_occ):
        ts = compute_next(recurrence, cursor, item.get('timezone'))
        if ts is None:
            break
        dt = datetime.fromtimestamp(ts, zone)
        if dt > end.astimezone(zone):
            break
        if dt >= start.astimezone(zone):
            out.append(dt)
        cursor = ts
    return out


def agenda(period: str = 'today') -> str:
    zone = tz(DEFAULT_TZ)
    now = datetime.now(zone)
    if period == 'tomorrow':
        start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1) - timedelta(seconds=1)
        label = 'amanhã'
    elif period == 'week':
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7) - timedelta(seconds=1)
        label = 'próximos 7 dias'
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1) - timedelta(seconds=1)
        label = 'hoje'

    dated: list[tuple[datetime, str, str]] = []
    routines: list[str] = []
    for item in list_schedules(status='active', limit=200):
        rec = item.get('recurrence') or {}
        if rec.get('freq') == 'interval':
            occurrences = _preview(item, start, end, 2)
            if occurrences:
                routines.append(f"- {item.get('message')} — {humanize(rec)}")
            continue
        for dt in _preview(item, start, end, 12):
            dated.append((dt, str(item.get('message') or item.get('title')), str(item.get('kind') or 'agenda')))

    try:
        from task_manager import list_tasks
        for task in list_tasks(status='todo'):
            due = str(task.get('due') or '').strip()
            if not due:
                continue
            try:
                dt = datetime.fromisoformat(due)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=zone)
            except Exception:
                try:
                    d = datetime.fromisoformat(due + 'T18:00:00').replace(tzinfo=zone)
                    dt = d
                except Exception:
                    continue
            if start <= dt <= end:
                dated.append((dt, f"Tarefa: {task.get('title')}", 'task'))
    except Exception:
        pass

    dated.sort(key=lambda x: x[0])
    lines = [f'📅 Sua agenda — {label}']
    if not dated and not routines:
        lines.append('Nenhum compromisso registrado para esse período.')
        return '\n'.join(lines)
    for dt, text, kind in dated[:30]:
        prefix = dt.strftime('%d/%m %H:%M') if period == 'week' else dt.strftime('%H:%M')
        lines.append(f'- {prefix} — {text}')
    if routines:
        lines.append('\nRotinas ativas:')
        lines.extend(routines[:10])
    return '\n'.join(lines)


def handle(text: str) -> str | None:
    raw = str(text or '').strip()
    if not raw:
        return None
    t = norm(raw)

    if any(x in t for x in ('o que tenho hoje', 'agenda de hoje', 'minha agenda hoje', 'meu dia', 'cronograma de hoje')):
        return agenda('today')
    if any(x in t for x in ('o que tenho amanha', 'agenda de amanha', 'minha agenda amanha', 'cronograma de amanha')):
        return agenda('tomorrow')
    if any(x in t for x in ('minha semana', 'agenda da semana', 'cronograma da semana', 'proximos 7 dias')):
        return agenda('week')
    if any(x in t for x in ('meus lembretes', 'minhas rotinas', 'listar lembretes', 'listar agenda', 'quais lembretes')):
        rows = list_schedules(status='active', limit=50)
        if not rows:
            return 'Nenhum lembrete, rotina ou evento ativo no Hermes.'
        lines = ['📋 Agenda interna do Hermes:']
        for item in rows:
            lines.append(f"- [{item['id']}] {item.get('message')} — {humanize(item.get('recurrence') or {})}")
        return '\n'.join(lines)

    if any(t.startswith(x) for x in ('pause ', 'pausar ', 'pare ', 'parar ')) and any(x in t for x in ('lembrete', 'rotina', 'evento', 'compromisso')):
        ref = _resolve_target(raw)
        if not ref:
            return 'Qual lembrete ou rotina você quer pausar?'
        item = pause(ref)
        return f"⏸️ Pausado: {item.get('message')}"
    if any(t.startswith(x) for x in ('retome ', 'retomar ', 'continue ')) and any(x in t for x in ('lembrete', 'rotina', 'evento', 'compromisso')):
        ref = _resolve_target(raw)
        if not ref:
            return 'Qual lembrete ou rotina você quer retomar?'
        item = resume(ref)
        return f"▶️ Retomado: {item.get('message')}"
    if any(t.startswith(x) for x in ('remova ', 'remover ', 'apague ', 'apagar ', 'cancele ', 'cancelar ')) and any(x in t for x in ('lembrete', 'rotina', 'evento', 'compromisso')):
        ref = _resolve_target(raw)
        if not ref:
            return 'Qual lembrete ou rotina você quer remover?'
        item = remove(ref)
        return f"🗑️ Removido da agenda: {item.get('message')}"

    m = re.search(r'\b(?:pause|pausa|suspenda)\s+(?:isso|o lembrete|a rotina)?\s*(?:por)?\s*(\d+)\s*(minuto|minutos|hora|horas|dia|dias)\b', t)
    if m:
        ref = _resolve_target(raw)
        if not ref:
            return 'Qual lembrete ou rotina você quer suspender?'
        value = int(m.group(1))
        unit = m.group(2)
        seconds = value * (60 if 'minuto' in unit else 3600 if 'hora' in unit else 86400)
        item = snooze(ref, int(time.time()) + seconds)
        return f"💤 Suspendi temporariamente: {item.get('message')}"

    if _creation_intent(raw):
        return create_from_text(raw)
    if _looks_temporal(raw):
        parsed = parse(raw)
        if parsed and parsed.get('needs_clarification'):
            return str(parsed['needs_clarification'])
    return None
