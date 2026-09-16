from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from task_manager import list_tasks
from temporal_parser import norm
from time_router import agenda

_ENTITY_WORDS = {
    'rotina', 'rotinas', 'lembrete', 'lembretes', 'alerta', 'alertas',
    'agenda', 'evento', 'eventos', 'compromisso', 'compromissos',
    'tarefa', 'tarefas', 'task', 'tasks',
}
_MUTATION_STEMS = (
    'cria', 'adicion', 'agenda', 'marca', 'cancel', 'exclu', 'remov', 'apag',
    'paus', 'retom', 'reagend', 'alter', 'mud', 'finaliz', 'conclu', 'termin',
)
_QUERY_TOKENS = {
    'oq', 'oque', 'que', 'qual', 'quais', 'quanto', 'quantos', 'tem', 'temos',
    'tenho', 'falta', 'faltou', 'ficou', 'previsto', 'marcado', 'programado',
}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r'[a-z0-9à-ÿ]+', norm(text)))


def _period(text: str) -> str | None:
    t = norm(text)
    tokens = _tokens(t)
    if 'amanha' in tokens:
        return 'tomorrow'
    if 'hoje' in tokens or 'hj' in tokens:
        return 'today'
    return None


def is_generic_day_query(text: str) -> bool:
    """Detecta consulta genérica sobre o dia pela estrutura, não por frase exata.

    A intenção é capturar perguntas do tipo "oq temos pra hoje?", "e amanhã?",
    "o que ficou para hoje" etc. Consultas que nomeiam uma entidade específica
    (tarefas, rotinas, agenda...) continuam nos roteadores especializados.
    """
    raw = str(text or '').strip()
    if not raw or _period(raw) is None:
        return False
    t = norm(raw)
    if any(stem in t for stem in _MUTATION_STEMS):
        return False
    tokens = _tokens(t)
    if tokens & _ENTITY_WORDS:
        return False
    return '?' in raw or bool(tokens & _QUERY_TOKENS)


def _target_date(period: str):
    today = datetime.now().date()
    return today if period == 'today' else today + timedelta(days=1)


def _task_sections(period: str) -> list[str]:
    target = _target_date(period)
    due: list[dict[str, Any]] = []
    overdue: list[dict[str, Any]] = []
    for task in list_tasks(status='todo'):
        raw = str(task.get('due') or '').strip()
        if not raw:
            continue
        try:
            day = datetime.fromisoformat(raw).date()
        except Exception:
            continue
        if day == target:
            due.append(task)
        elif period == 'today' and day < target:
            overdue.append(task)

    rank = {'high': 0, 'medium': 1, 'low': 2}
    due.sort(key=lambda x: (rank.get(str(x.get('priority') or 'medium'), 1), str(x.get('due') or '')))
    overdue.sort(key=lambda x: (rank.get(str(x.get('priority') or 'medium'), 1), str(x.get('due') or '')))

    lines: list[str] = []
    if due:
        lines.append('✅ Tarefas')
        for task in due[:8]:
            lines.append(f"- {task.get('title')}")
    if overdue:
        lines.append('⚠️ Atrasadas')
        for task in overdue[:5]:
            lines.append(f"- {task.get('title')}")
    return lines


def render(text: str) -> str | None:
    if not is_generic_day_query(text):
        return None
    period = _period(text) or 'today'
    label = 'hoje' if period == 'today' else 'amanhã'

    sections: list[str] = [f'📌 Seu dia {label}']
    try:
        schedule = agenda(period)
        if schedule:
            sections.extend(['', schedule])
    except Exception:
        sections.extend(['', '📅 Agenda indisponível no momento.'])

    task_lines = _task_sections(period)
    if task_lines:
        sections.extend([''] + task_lines)

    return '\n'.join(sections)
