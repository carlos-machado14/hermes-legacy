#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any


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


_PROFILES = {
    'fast': ComplexityProfile('fast', 20, 180, 4, 1600, 2, 1, 500, True, True, False),
    'normal': ComplexityProfile('normal', 60, 420, 10, 5000, 4, 3, 1600, True, True, False),
    'hard': ComplexityProfile('hard', 150, 900, 14, 8000, 6, 5, 3000, True, True, True),
    'mission': ComplexityProfile('mission', 180, 1200, 18, 12000, 8, 8, 5000, True, True, True),
}


def _profile(tier: str) -> ComplexityProfile:
    return _PROFILES[tier]


def classify(text: str) -> ComplexityProfile:
    raw = str(text or '').strip()
    forced = (os.getenv('HERMES_COMPLEXITY') or '').strip().casefold()
    if forced in _PROFILES:
        return _profile(forced)
    if not raw:
        return _profile('fast')

    words = len(re.findall(r'\S+', raw))
    chars = len(raw)
    lines = raw.count('\n') + 1
    structural_weight = 0
    structural_weight += min(3, raw.count('```') // 2)
    structural_weight += 1 if lines >= 20 else 0
    structural_weight += 1 if lines >= 50 else 0

    if chars >= 1800 or words >= 260 or structural_weight >= 3:
        return _profile('hard')
    if chars <= 80 and words <= 14 and lines <= 3:
        return _profile('fast')
    return _profile('normal')


def sla_for(text: str) -> dict[str, Any]:
    profile = classify(text)
    return {
        'tier': profile.tier,
        'timeout_seconds': profile.timeout_seconds,
        'max_output_tokens': profile.max_output_tokens,
        'prefer_hard_model': profile.prefer_hard_model,
    }
