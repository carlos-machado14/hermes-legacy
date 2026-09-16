#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any

_EXACT_REPLY_RE = re.compile(r'^\s*(?:responda|responde)\s+(?:apenas|somente)\s*:?\s*.+$', re.I | re.S)

_MISSION_HINTS = (
    'missão:', 'missao:', 'execute até finalizar', 'execute ate finalizar', 'trabalhe até concluir',
    'trabalhe ate concluir', 'faça até finalizar', 'faca ate finalizar', 'continue sozinho até',
    'continue sozinho ate', 'até concluir', 'ate concluir',
)
_HARD_HINTS = (
    'analise profundamente', 'análise profunda', 'detalhadamente', 'passo a passo', 'arquitetura',
    'refatore', 'refatorar', 'investigue', 'diagnostique', 'causa raiz', 'root cause',
    'revise o projeto', 'otimize tudo', 'corrija tudo',
)
_RESEARCH_HINTS = (
    'pesquise', 'pesquisar', 'procure', 'buscar', 'busque', 'encontre', 'encontrar', 'colete', 'coletar',
    'investigue', 'levante', 'mapear', 'audite', 'auditar', 'analise empresas', 'possível cliente', 'possivel cliente',
    'lead', 'presença digital', 'presenca digital', 'traga os dados', 'trazer os dados', 'dados de 1 empresa',
    'precisa de um site', 'precisando de um site',
)
_MULTI_RESULT_HINTS = (
    'todos os dados', 'com todos os dados', 'links', 'imagens', 'contatos', 'telefone', 'whatsapp', 'instagram',
    'compare', 'comparar', 'o melhor', 'melhor opção', 'melhor opcao', 'verifique', 'validar', 'fontes',
)
_IMPLEMENT_HINTS = (
    'implemente', 'implementar', 'desenvolva', 'desenvolver', 'corrija o projeto', 'aplique no projeto',
    'faça tudo', 'faca tudo', 'implemente tudo', 'implementar tudo', 'refatore o projeto', 'revise todo', 'revise toda',
)
_PERSONAL_HINTS = (
    'meu ', 'minha ', 'meus ', 'minhas ', 'sobre mim', 'de mim', 'para mim', 'pra mim', 'lembra de',
    'lembre de', 'meu perfil', 'meus dados', 'meu objetivo', 'meus objetivos', 'minha tarefa', 'minhas tarefas',
    'meu projeto', 'meus projetos', 'minha rotina', 'minhas rotinas', 'meus gastos', 'minhas despesas',
    'minhas finanças', 'minhas financas',
)
_FOLLOWUP_HINTS = (
    'isso', 'essa', 'esse', 'esta', 'este', 'aquilo', 'ela', 'ele', 'dessa', 'desse', 'continue', 'continua',
    'continuar', 'pode seguir', 'pode continuar', 'e agora', 'e depois', 'mais detalhes', 'mais detalhe',
    'explique melhor', 'melhore isso', 'faça isso', 'faca isso', 'pode fazer', 'sim', 'não', 'nao',
)

@dataclass(frozen=True)
class ComplexityProfile:
    tier: str
    timeout_seconds: int
    max_output_tokens: int
    recent_items: int
    recent_chars: int
    personal_items: int
    memory_limit: int
    memory_chars: int
    use_recent: bool
    use_personal: bool
    prefer_hard_model: bool
    def to_dict(self) -> dict[str, Any]: return asdict(self)

# Conversas normais agora sempre carregam uma janela curta de contexto. Isso evita
# que cada mensagem do Telegram pareça uma nova conversa sem aumentar demais o prompt.
_PROFILES = {
    'fast': ComplexityProfile('fast', 12, 120, 2, 550, 0, 0, 0, True, False, False),
    'normal': ComplexityProfile('normal', 45, 280, 6, 2400, 1, 1, 420, True, False, False),
    'hard': ComplexityProfile('hard', 120, 700, 8, 3600, 3, 3, 1400, True, False, True),
    'mission': ComplexityProfile('mission', 30, 900, 10, 5000, 4, 4, 1800, True, True, True),
}


def _contains(text: str, hints: tuple[str, ...]) -> bool:
    low = text.casefold(); return any(h in low for h in hints)


def _looks_like_followup(text: str) -> bool:
    low = text.casefold().strip()
    if not low or len(low) > 220: return False
    if low in {'sim','não','nao','ok','pode','pode fazer','continue','continua'}: return True
    return any(h in low for h in _FOLLOWUP_HINTS)


def _looks_personal(text: str) -> bool: return _contains(text, _PERSONAL_HINTS)


def _profile(tier: str, *, use_recent: bool | None = None, use_personal: bool | None = None) -> ComplexityProfile:
    values = _PROFILES[tier].to_dict()
    if use_recent is not None: values['use_recent'] = bool(use_recent)
    if use_personal is not None: values['use_personal'] = bool(use_personal)
    return ComplexityProfile(**values)


def _mission_score(raw: str) -> int:
    low = raw.casefold(); score = 0
    if any(low.startswith(h) for h in _MISSION_HINTS): score += 6
    research = sum(1 for h in _RESEARCH_HINTS if h in low)
    multi = sum(1 for h in _MULTI_RESULT_HINTS if h in low)
    implementation = sum(1 for h in _IMPLEMENT_HINTS if h in low)
    score += min(research, 2) * 2
    score += min(multi, 3)
    score += min(implementation, 2) * 2
    if research and multi: score += 2
    if research and any(x in low for x in ('empresa','cliente','negócio','negocio','site','cidade','colombo')): score += 2
    if implementation and any(x in low for x in ('projeto','repo','repositório','repositorio','sistema')): score += 2
    words = len(re.findall(r'\S+', raw))
    if words >= 80: score += 2
    elif words >= 45: score += 1
    return score


def classify(text: str) -> ComplexityProfile:
    raw = str(text or '').strip(); low = raw.casefold()
    forced = (os.getenv('HERMES_COMPLEXITY') or '').strip().casefold()
    if forced in _PROFILES:
        base = _PROFILES[forced]
        return _profile(forced, use_recent=True, use_personal=base.use_personal or _looks_personal(raw))
    if not raw: return _PROFILES['fast']
    if _EXACT_REPLY_RE.match(raw): return _PROFILES['fast']

    mission_score = _mission_score(raw)
    if mission_score >= 6:
        return _profile('mission', use_recent=True, use_personal=_looks_personal(raw) or None)

    words = len(re.findall(r'\S+', raw)); hard_score = 0
    if words >= 110 or len(raw) >= 750: hard_score += 2
    elif words >= 65 or len(raw) >= 420: hard_score += 1
    hard_score += sum(1 for h in _HARD_HINTS if h in low)
    if re.search(r'\b(?:analise|compare|investigue|diagnostique|planeje|refatore)\b', low): hard_score += 1
    if hard_score >= 2:
        return _profile('hard', use_recent=True, use_personal=_looks_personal(raw))
    return _profile('normal', use_recent=True, use_personal=_looks_personal(raw))


def sla_for(text: str) -> dict[str, Any]:
    p = classify(text)
    return {'tier': p.tier, 'timeout_seconds': p.timeout_seconds, 'max_output_tokens': p.max_output_tokens, 'prefer_hard_model': p.prefer_hard_model}
