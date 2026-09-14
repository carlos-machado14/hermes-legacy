from __future__ import annotations

from typing import Any

AGENTS: dict[str, dict[str, Any]] = {
    'general': {
        'title': 'General Assistant',
        'domains': ['personal','knowledge','control'],
        'purpose': 'Conversar, organizar contexto, decidir quando usar ferramentas e coordenar outras especialidades.',
    },
    'researcher': {
        'title': 'Researcher',
        'domains': ['research','knowledge'],
        'purpose': 'Pesquisar, navegar, coletar evidências, comparar fontes e produzir sínteses confiáveis.',
    },
    'developer': {
        'title': 'Developer',
        'domains': ['developer'],
        'purpose': 'Entender código, modificar projetos, testar, revisar diffs e preparar entregas versionadas.',
    },
    'devops': {
        'title': 'DevOps',
        'domains': ['devops'],
        'purpose': 'Inspecionar infraestrutura, serviços, containers, logs e executar recuperação segura.',
    },
    'business': {
        'title': 'Business',
        'domains': ['business'],
        'purpose': 'Trabalhar com receita, CRM, oportunidades, ofertas, estratégia e acompanhamento comercial.',
    },
    'personal': {
        'title': 'Personal Assistant',
        'domains': ['personal'],
        'purpose': 'Objetivos, tarefas, agenda, lembretes, planejamento diário e decisões pessoais.',
    },
    'communication': {
        'title': 'Communication',
        'domains': ['communication'],
        'purpose': 'Preparar e, com política de aprovação, enviar mensagens por canais conectados.',
    },
    'finance': {
        'title': 'Finance',
        'domains': ['finance'],
        'purpose': 'Analisar metas financeiras, receitas, despesas e cenários sem inventar transações.',
    },
    'reviewer': {
        'title': 'Reviewer',
        'domains': ['control'],
        'purpose': 'Validar qualidade, evidências e Definition of Done antes de encerrar missões.',
    },
}


def list_agents() -> dict[str, dict[str, Any]]:
    return AGENTS.copy()


def agent_for_domain(domain: str) -> str:
    for name, spec in AGENTS.items():
        if domain in spec.get('domains', []):
            return name
    return 'general'
