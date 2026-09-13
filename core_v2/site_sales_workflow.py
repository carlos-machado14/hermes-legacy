#!/usr/bin/env python3
from __future__ import annotations

import json, time
from pathlib import Path
from typing import Any

from context_builder import primary_goal
from goal_manager import update_goal
from task_manager import create_task, list_tasks
from decision_log import record
try:
    from memory_vault import write_note
except Exception:
    write_note = None

STATE_DIR = Path.home() / '.hermes/core-v2/state'
FILE = STATE_DIR / 'site_sales_workflow.json'

PIPELINE = [
    'Encontrar uma empresa sem site ou com site muito antigo',
    'Coletar dados públicos da empresa, serviços, contatos, identidade e referências',
    'Analisar problemas do site atual ou ausência de presença digital',
    'Definir estrutura, proposta visual e CTA principal',
    'Gerar uma nova versão do site/demonstração',
    'Revisar conteúdo, responsividade, velocidade e conversão',
    'Salvar empresa como lead e registrar oportunidade',
    'Preparar abordagem personalizada com link/demo',
    'Fazer contato após aprovação do usuário',
    'Acompanhar resposta, follow-up e resultado no CRM',
]


def load() -> dict[str, Any]:
    try:
        data = json.loads(FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {'enabled': False}
    except Exception:
        return {'enabled': False}


def _save(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _ensure_tasks(goal_id: str) -> int:
    existing = list_tasks(goal_id=goal_id)
    titles = {str(x.get('title') or '').casefold() for x in existing}
    created = 0
    for i, title in enumerate(PIPELINE, 1):
        task_title = f'[Sites Diário] {title}'
        if task_title.casefold() in titles:
            continue
        create_task(
            task_title,
            goal_id=goal_id,
            priority='high' if i <= 6 else 'medium',
            kind='daily_site_sales_step',
            metadata={'workflow': 'daily_site_sales', 'step': i, 'recurring': True},
        )
        created += 1
    return created


def configure_for_primary_goal() -> str:
    goal = primary_goal()
    if not goal:
        return 'Não encontrei objetivo ativo para vincular essa estratégia.'

    strategy = (
        'Estratégia principal de execução diária: todos os dias selecionar uma empresa que não possua site '
        'ou que tenha um site muito antigo/desatualizado; coletar dados públicos da empresa; analisar presença '
        'digital e problemas; criar uma nova versão de site/demonstração; registrar como lead; preparar abordagem '
        'personalizada; e acompanhar o resultado no CRM. A meta operacional é produzir 1 demonstração/site por dia.'
    )
    old = str(goal.get('notes') or '').strip()
    if strategy.casefold() not in old.casefold():
        merged = (old + '\n\n' + strategy).strip() if old else strategy
        goal = update_goal(goal['id'], notes=merged)

    created = _ensure_tasks(goal['id'])
    data = {
        'enabled': True,
        'goal_id': goal['id'],
        'goal_title': goal['title'],
        'daily_target': 1,
        'selection_rule': 'empresa sem site ou com site antigo/desatualizado',
        'pipeline': PIPELINE,
        'updated_at': int(time.time()),
    }
    _save(data)
    record('daily_site_sales_strategy_enabled', strategy, metadata={'goal_id': goal['id']})

    if write_note is not None:
        try:
            body = (
                f'Objetivo relacionado: [[{goal["title"]}]]\n\n'
                'Meta diária: **1 empresa / 1 demonstração de site por dia**\n\n'
                'Critério de seleção: empresa sem site ou com site muito antigo/desatualizado.\n\n'
                '## Pipeline\n' + '\n'.join(f'{i}. {x}' for i, x in enumerate(PIPELINE, 1)) +
                '\n\n## Regra de segurança\nContato externo, publicação em produção, compra, pagamento ou envio em nome do usuário exigem aprovação.'
            )
            write_note('business', 'Estratégia diária de criação de sites', body, filename='estrategia-diaria-sites.md')
        except Exception:
            pass

    return (
        f'Estratégia diária vinculada ao objetivo: {goal["title"]}.\n'
        'Meta operacional: 1 empresa por dia → coletar dados → analisar → criar demo/site → registrar lead → preparar abordagem → acompanhar CRM.\n'
        f'Etapas recorrentes cadastradas: {len(PIPELINE)} (novas agora: {created}).\n'
        'Quando GitHub/deploy estiverem conectados, a etapa de geração e publicação da demo poderá ser executada pelo Hermes; contato externo continuará exigindo sua aprovação.'
    )


def summary() -> str:
    data = load()
    if not data.get('enabled'):
        return 'A estratégia diária de sites ainda não está ativa.'
    out = [
        'Estratégia diária de sites: ATIVA',
        f"Objetivo: {data.get('goal_title')}",
        f"Meta diária: {data.get('daily_target', 1)} empresa/site",
        f"Seleção: {data.get('selection_rule')}",
        'Fluxo:',
    ]
    for i, step in enumerate(data.get('pipeline') or PIPELINE, 1):
        out.append(f'{i}. {step}')
    return '\n'.join(out)
