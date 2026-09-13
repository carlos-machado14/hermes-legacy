#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

SKILLS: dict[str, dict[str, Any]] = {
    'goals': {'description': 'Criar, acompanhar e concluir objetivos pessoais/profissionais.', 'mode': 'deterministic'},
    'tasks': {'description': 'Gerenciar tarefas e próximos passos.', 'mode': 'deterministic'},
    'money': {'description': 'Planejar metas de receita e oportunidades.', 'mode': 'hybrid'},
    'research': {'description': 'Estruturar pesquisas e transformar achados em ações.', 'mode': 'hybrid'},
    'routines': {'description': 'Criar e administrar rotinas e lembretes.', 'mode': 'deterministic'},
    'projects': {'description': 'Acompanhar projetos e seus estados.', 'mode': 'deterministic'},
    'operations': {'description': 'Saúde da VPS, serviços e recuperação segura.', 'mode': 'deterministic'},
    'conversation': {'description': 'Raciocínio geral com o modelo local quando necessário.', 'mode': 'llm'},
}


def list_skills() -> list[dict[str, Any]]:
    return [{'name': name, **meta} for name, meta in SKILLS.items()]


def describe() -> str:
    out = ['Skills do Hermes v3:']
    for name, meta in SKILLS.items(): out.append(f"- {name}: {meta['description']} [{meta['mode']}]")
    return '\n'.join(out)
