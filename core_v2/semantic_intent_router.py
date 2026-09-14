#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from typing import Any, Callable

LABELS: dict[str, tuple[str, str]] = {
    'CRON_CREATE': ('cron', 'create'),
    'CRON_STATUS': ('cron', 'status'),
    'CRON_LIST': ('cron', 'list'),
    'CRON_UPDATE_BRIEF': ('cron', 'update_brief'),
    'CRON_PAUSE': ('cron', 'pause'),
    'CRON_RESUME': ('cron', 'resume'),
    'CRON_RUN': ('cron', 'run'),
    'CRON_REMOVE': ('cron', 'remove'),
    'FINANCE': ('finance', 'unknown'),
    'RESEARCH': ('research', 'unknown'),
    'DEVELOPER': ('developer', 'unknown'),
    'DEVOPS': ('devops', 'unknown'),
    'MEMORY': ('memory', 'unknown'),
    'MISSION': ('mission', 'unknown'),
    'CONNECTED': ('connected', 'unknown'),
    'ASSISTANT': ('assistant', 'unknown'),
    'CHAT': ('chat', 'unknown'),
}

_SPECIALIZED_HINTS = (
    # Cron / automação
    'rotina', 'rotinas', 'cron', 'crons', 'lembrete', 'lembretes', 'brief', 'briefing',
    'job', 'jobs', 'agende', 'agendar', 'todo dia', 'todos os dias', 'diariamente',
    'toda segunda', 'toda terça', 'toda terca', 'toda quarta', 'toda quinta', 'toda sexta',
    'me lembre', 'lembre-me',
    # Financeiro
    'gasto', 'gastos', 'despesa', 'despesas', 'receita', 'assinatura', 'assinaturas',
    'financeiro', 'finanças', 'financas', 'r$', 'pix', 'cartão', 'cartao',
    # Pesquisa
    'pesquise', 'pesquisar', 'procure', 'buscar', 'busque', 'notícia', 'noticia', 'notícias', 'noticias',
    # Desenvolvimento / infra
    'código', 'codigo', 'repo', 'repositório', 'repositorio', 'github', 'bug', 'flutter', 'nest', 'react',
    'docker', 'container', 'vps', 'servidor', 'systemd', 'deploy', 'nginx', 'caddy', 'redis',
    # Memória / missão / integrações
    'lembra de', 'lembre de', 'memória', 'memoria', 'missão', 'missao',
    'email', 'e-mail', 'agenda', 'calendário', 'calendario', 'whatsapp', 'telegram',
)

_CRON_HINTS = (
    'rotina', 'rotinas', 'cron', 'crons', 'lembrete', 'lembretes', 'brief', 'briefing',
    'job', 'jobs', 'agende', 'agendar', 'todo dia', 'todos os dias', 'diariamente',
    'toda segunda', 'toda terça', 'toda terca', 'toda quarta', 'toda quinta', 'toda sexta',
    'me lembre', 'lembre-me',
)

_FOLLOWUP_MARKERS = (
    'isso', 'essa', 'esse', 'esta', 'este', 'ela', 'ele', 'aquela', 'aquele',
    'assim', 'agora', 'pode fazer', 'pode ser', 'sim', 'não', 'nao', 'continua',
    'continue', 'melhore', 'melhor', 'mais detalhe', 'mais detalhes', 'mais completo',
    'mais completa', 'mais curto', 'mais resumido', 'sem link', 'com link',
)


def _norm(text: str) -> str:
    return re.sub(r'\s+', ' ', str(text or '').casefold()).strip()


def _label_from_raw(raw: str) -> str | None:
    """Aceita somente uma etiqueta válida; respostas ambíguas caem para o fluxo normal."""
    text = str(raw or '').strip().upper()
    if not text:
        return None
    labels = [token for token in re.findall(r'[A-Z][A-Z_]+', text) if token in LABELS]
    unique = list(dict.fromkeys(labels))
    return unique[0] if len(unique) == 1 else None


def _is_contextual_followup(text: str) -> bool:
    t = _norm(text)
    if not t or len(t) > 180:
        return False
    if t in {'sim', 'não', 'nao', 'pode', 'pode fazer', 'faça', 'faca', 'continue', 'continua'}:
        return True
    return any(re.search(rf'\b{re.escape(marker)}\b', t) for marker in _FOLLOWUP_MARKERS)


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    t = _norm(text)
    return any(hint in t for hint in hints)


def _should_classify(text: str, recent: str) -> bool:
    # Mensagem geral deve ir direto ao Hermes normal. Isso economiza uma chamada
    # ao modelo pequeno e impede que contexto antigo force uma rota especializada.
    if _contains_any(text, _SPECIALIZED_HINTS):
        return True
    return _is_contextual_followup(text) and _contains_any(recent, _SPECIALIZED_HINTS)


def _cron_route_is_safe(label: str, text: str, recent: str) -> bool:
    if not label.startswith('CRON_'):
        return True
    # Operações de cron nunca podem nascer apenas de contexto velho. Exigimos
    # evidência na mensagem atual ou um follow-up curto e inequívoco sobre cron.
    if _contains_any(text, _CRON_HINTS):
        return True
    return _is_contextual_followup(text) and _contains_any(recent, _CRON_HINTS)


def _classify_label(text: str, recent: str, llm: Callable[..., str]) -> str | None:
    system = (
        'Você é somente o classificador de intenção do Hermes. NÃO responda ao usuário. '
        'Escolha EXATAMENTE UMA etiqueta e escreva somente a etiqueta, sem explicação.\n\n'
        'Regra principal: a MENSAGEM ATUAL tem prioridade absoluta. O CONTEXTO RECENTE só serve para resolver referências '
        'claras como "isso", "essa rotina", "rode agora" ou "pode fazer". Nunca transforme uma nova pergunta independente '
        'em ação de cron apenas porque o assunto anterior era rotinas.\n\n'
        'Etiquetas permitidas:\n'
        'CRON_CREATE = criar nova rotina/tarefa agendada ou recorrente\n'
        'CRON_STATUS = diagnosticar se uma rotina executou, falhou ou seu estado\n'
        'CRON_LIST = listar rotinas\n'
        'CRON_UPDATE_BRIEF = mudar qualidade, profundidade, formato, links ou conteúdo das entregas automáticas/briefings que o usuário recebe\n'
        'CRON_PAUSE = pausar rotina\n'
        'CRON_RESUME = retomar rotina\n'
        'CRON_RUN = executar rotina agora\n'
        'CRON_REMOVE = remover rotina\n'
        'FINANCE = consultar ou alterar finanças pessoais\n'
        'RESEARCH = pesquisar informação externa atual\n'
        'DEVELOPER = código, repo, projeto, implementação, bug\n'
        'DEVOPS = VPS, processo, serviço, container, infraestrutura\n'
        'MEMORY = memória/contexto pessoal\n'
        'MISSION = tarefa longa/durável\n'
        'CONNECTED = agenda/email/github/whatsapp via integração\n'
        'ASSISTANT = ação geral do assistente que não cai acima\n'
        'CHAT = conversa comum sem ação especializada\n\n'
        'Importante: quando o usuário reclama que algo que recebe automaticamente está raso, superficial, curto, sem contexto, '
        'ou quer entender melhor sem abrir links/sair do Telegram, isso é CRON_UPDATE_BRIEF. '
        'Quando ele pergunta se uma rotina rodou, isso é CRON_STATUS. '
        'Quando quer uma nova rotina, CRON_CREATE.'
    )
    use_recent = recent[-1200:] if _is_contextual_followup(text) else ''
    prompt = (
        f'CONTEXTO RECENTE:\n{use_recent or "(não necessário para esta mensagem)"}\n\n'
        f'MENSAGEM ATUAL:\n{text}\n\n'
        'ETIQUETA:'
    )
    try:
        raw = llm(prompt, system=system, max_tokens=24)
    except Exception:
        return None
    return _label_from_raw(raw)


def _extract_brief_params(text: str, recent: str, llm: Callable[..., str]) -> dict[str, Any]:
    system = (
        'Extraia preferências de briefing. Retorne SOMENTE JSON válido e curto. '
        'Campos possíveis: detail_level (short|normal|detailed), include_links (boolean), summary_without_link (boolean). '
        'Não invente campos. Se o usuário quer mais contexto, mais profundidade ou diz que está superficial, detail_level=detailed. '
        'Se quer entender sem abrir link/sair do Telegram, summary_without_link=true. '
        'Se quer manter links apenas como fonte, include_links=true.'
    )
    use_recent = recent[-800:] if _is_contextual_followup(text) else ''
    prompt = (
        f'CONTEXTO:\n{use_recent or "(não necessário)"}\n\n'
        f'MENSAGEM:\n{text}\n\nJSON:'
    )
    try:
        raw = llm(prompt, system=system, max_tokens=90)
    except Exception:
        return {}
    raw = str(raw or '').strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        m = re.search(r'\{.*?\}', raw, re.DOTALL)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def classify(text: str, recent_context: str, llm: Callable[..., str]) -> dict[str, Any] | None:
    current = str(text or '').strip()
    if not current:
        return None
    recent = str(recent_context or '')[-1800:]

    # Para conversa geral, não gaste uma chamada só para classificar. O fluxo
    # normal do Hermes responde diretamente. O roteador semântico entra apenas
    # quando há indício real de domínio especializado ou follow-up contextual.
    if not _should_classify(current, recent):
        return None

    label = _classify_label(current, recent, llm)
    if not label:
        return None

    # Guarda crítica: uma classificação errada do modelo pequeno jamais pode
    # executar/listar/alterar cron apenas por contaminação do histórico recente.
    if not _cron_route_is_safe(label, current, recent):
        return None

    route, action = LABELS[label]
    params: dict[str, Any] = {}
    confidence = 0.88 if label != 'CHAT' else 0.65

    if label == 'CRON_UPDATE_BRIEF':
        params = _extract_brief_params(current, recent, llm)
        if not params:
            params = {
                'detail_level': 'detailed',
                'summary_without_link': True,
                'include_links': True,
            }

    return {
        'route': route,
        'action': action,
        'confidence': confidence,
        'target': None,
        'params': params,
        'reason': f'classificado como {label}',
    }
