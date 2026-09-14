from __future__ import annotations

import re
from typing import Any

from agent_catalog import agent_for_domain

DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    'developer': ('repo','github','código','codigo','flutter','dart','nestjs','api','bug','build','teste','testes','commit','branch','pr','pull request','deploy','frontend','backend'),
    'research': ('pesquise','pesquisa','procure','buscar','busque','descubra','compare','site','web','navegue','fonte','fontes','notícia','noticia'),
    'devops': ('vps','docker','container','systemd','serviço','servico','log','logs','cpu','ram','disco','caddy','redis','dokploy','servidor'),
    'business': ('cliente','lead','crm','venda','vender','receita','negócio','negocio','proposta','oportunidade','marketing','ticket','follow-up'),
    'finance': ('dinheiro','financeiro','gasto','gastos','despesa','despesas','receita','orçamento','orcamento','assinatura','assinaturas','economizar','lucro'),
    'communication': ('email','e-mail','whatsapp','telegram','mensagem','responder','enviar','mande','envie','contato'),
    'personal': ('objetivo','objetivos','tarefa','tarefas','hoje','amanhã','amanha','semana','rotina','lembrete','agenda','prioridade','planejamento'),
    'knowledge': ('lembra','memória','memoria','contexto','documento','arquivo','arquivos','conhecimento','histórico','historico'),
}


def classify(text: str) -> dict[str, Any]:
    low = text.casefold()
    scores: dict[str, int] = {domain: 0 for domain in DOMAIN_KEYWORDS}
    for domain, words in DOMAIN_KEYWORDS.items():
        for word in words:
            if word in low:
                scores[domain] += 2 if ' ' in word else 1

    # Strong intent hints.
    if re.search(r'\b(crie|corrija|implemente|altere)\b.*\b(código|codigo|repo|projeto|app|site)\b', low):
        scores['developer'] += 4
    if re.search(r'\b(pesquise|procure|busque|encontre|descubra)\b', low):
        scores['research'] += 3
    if re.search(r'\b(reinicie|restart|suba|derrube|verifique)\b.*\b(serviço|servico|container|vps|docker)\b', low):
        scores['devops'] += 4

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    primary, score = ordered[0]
    if score <= 0:
        primary = 'personal'
    secondary = [name for name, value in ordered[1:4] if value > 0]
    return {
        'primary_domain': primary,
        'secondary_domains': secondary,
        'agent': agent_for_domain(primary),
        'scores': {k: v for k, v in scores.items() if v > 0},
    }
