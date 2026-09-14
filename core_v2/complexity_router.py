#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any

_EXACT_REPLY_RE = re.compile(
    r'^\s*(?:responda|responde)\s+(?:apenas|somente)\s*:?\s*.+$',
    re.IGNORECASE | re.DOTALL,
)

_MISSION_HINTS = (
    'missão:', 'missao:', 'execute até finalizar', 'execute ate finalizar',
    'trabalhe até concluir', 'trabalhe ate concluir', 'faça até finalizar',
    'faca ate finalizar', 'continue sozinho até', 'continue sozinho ate',
)

_HARD_HINTS = (
    'analise profundamente', 'análise profunda', 'analise completo', 'analise completa',
    'detalhadamente', 'passo a passo', 'arquitetura', 'refatore', 'refatorar',
    'compare opções', 'compare opcoes', 'investigue', 'diagnostique', 'planeje completo',
    'planeje completa', 'implemente completo', 'implemente completa', 'revise o projeto',
    'revise todo', 'revise toda', 'pesquisa completa', 'pesquise profundamente',
    'root cause', 'causa raiz', 'otimize tudo', 'corrija tudo',
)

_PERSONAL_HINTS = (
    'meu ', 'minha ', 'meus ', 'minhas ', 'sobre mim', 'de mim', 'para mim', 'pra mim',
    'lembra de', 'lembre de', 'meu perfil', 'meus dados', 'meu objetivo', 'meus objetivos',
    'minha tarefa', 'minhas tarefas', 'meu projeto', 'meus projetos', 'minha rotina',
    'minhas rotinas', 'meus gastos', 'minhas despesas', 'minhas finanças', 'minhas financas',
)

_FOLLOWUP_HINTS = (
    'isso', 'essa', 'esse', 'esta', 'este', 'aquilo', 'ela', 'ele', 'dessa', 'desse',
    'continue', 'continua', 'continuar', 'pode seguir', 'pode continuar', 'e agora',
    'e depois', 'mais detalhes', 'mais detalhe', 'explique melhor', 'melhore isso',
    'faça isso', 'faca isso', 'pode fazer', 'sim', 'não', 'nao',
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_PROFILES: dict[str, ComplexityProfile] = {
    'fast': ComplexityProfile(
        tier='fast',
        timeout_seconds=12,
        max_output_tokens=120,
        recent_items=0,
        recent_chars=0,
        personal_items=0,
        memory_limit=0,
        memory_chars=0,
        use_recent=False,
        use_personal=False,
        prefer_hard_model=False,
    ),
    'normal': ComplexityProfile(
        tier='normal',
        timeout_seconds=45,
        max_output_tokens=280,
        recent_items=2,
        recent_chars=550,
        personal_items=1,
        memory_limit=1,
        memory_chars=420,
        use_recent=False,
        use_personal=False,
        prefer_hard_model=False,
    ),
    'hard': ComplexityProfile(
        tier='hard',
        timeout_seconds=120,
        max_output_tokens=700,
        recent_items=4,
        recent_chars=1400,
        personal_items=3,
        memory_limit=3,
        memory_chars=1400,
        use_recent=True,
        use_personal=False,
        prefer_hard_model=True,
    ),
    'mission': ComplexityProfile(
        tier='mission',
        timeout_seconds=300,
        max_output_tokens=900,
        recent_items=5,
        recent_chars=1800,
        personal_items=4,
        memory_limit=4,
        memory_chars=1800,
        use_recent=True,
        use_personal=True,
        prefer_hard_model=True,
    ),
}


def _contains(text: str, hints: tuple[str, ...]) -> bool:
    low = text.casefold()
    return any(hint in low for hint in hints)


def _looks_like_followup(text: str) -> bool:
    low = text.casefold().strip()
    if not low or len(low) > 220:
        return False
    if low in {'sim', 'não', 'nao', 'ok', 'pode', 'pode fazer', 'continue', 'continua'}:
        return True
    return any(hint in low for hint in _FOLLOWUP_HINTS)


def _looks_personal(text: str) -> bool:
    return _contains(text, _PERSONAL_HINTS)


def _profile(tier: str, *, use_recent: bool | None = None, use_personal: bool | None = None) -> ComplexityProfile:
    base = _PROFILES[tier]
    values = base.to_dict()
    if use_recent is not None:
        values['use_recent'] = bool(use_recent)
    if use_personal is not None:
        values['use_personal'] = bool(use_personal)
    return ComplexityProfile(**values)


def classify(text: str) -> ComplexityProfile:
    raw = str(text or '').strip()
    low = raw.casefold()

    forced = (os.getenv('HERMES_COMPLEXITY') or '').strip().casefold()
    if forced in _PROFILES:
        base = _PROFILES[forced]
        return _profile(
            forced,
            use_recent=base.use_recent or _looks_like_followup(raw),
            use_personal=base.use_personal or _looks_personal(raw),
        )

    if not raw:
        return _PROFILES['fast']

    if _EXACT_REPLY_RE.match(raw):
        return _PROFILES['fast']

    if any(low.startswith(hint) for hint in _MISSION_HINTS):
        return _PROFILES['mission']

    word_count = len(re.findall(r'\S+', raw))
    hard_score = 0
    if word_count >= 110 or len(raw) >= 750:
        hard_score += 2
    elif word_count >= 65 or len(raw) >= 420:
        hard_score += 1

    for hint in _HARD_HINTS:
        if hint in low:
            hard_score += 1

    if re.search(r'\b(?:analise|compare|investigue|diagnostique|planeje|implemente|refatore)\b', low):
        hard_score += 1

    if hard_score >= 2:
        return _profile(
            'hard',
            use_recent=_looks_like_followup(raw),
            use_personal=_looks_personal(raw),
        )

    return _profile(
        'normal',
        use_recent=_looks_like_followup(raw),
        use_personal=_looks_personal(raw),
    )


def sla_for(text: str) -> dict[str, Any]:
    profile = classify(text)
    return {
        'tier': profile.tier,
        'timeout_seconds': profile.timeout_seconds,
        'max_output_tokens': profile.max_output_tokens,
        'prefer_hard_model': profile.prefer_hard_model,
    }
