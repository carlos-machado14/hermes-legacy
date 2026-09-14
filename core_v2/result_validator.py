from __future__ import annotations

import re
from typing import Any

BAD_MARKERS = (
    'não consegui', 'nao consegui', 'erro:', 'timed out', 'timeout',
    'tente novamente', 'não foi possível', 'nao foi possivel',
)


def validate_step(step: dict[str, Any], output: str) -> tuple[bool, str]:
    text = (output or '').strip()
    if len(text) < 20:
        return False, 'resultado_curto_ou_vazio'
    low = text.casefold()
    if any(marker in low for marker in BAD_MARKERS):
        return False, 'resultado_indica_falha'
    mode = str(step.get('validator') or 'quality')
    if mode == 'evidence':
        has_signal = bool(re.search(r'https?://|\b(?:telefone|whatsapp|endereço|endereco|instagram|site|fonte)\b', low))
        if not has_signal:
            return False, 'faltam_evidencias_ou_dados_verificaveis'
    return True, 'ok'


def validate_final(request: str, outputs: list[str]) -> tuple[bool, str]:
    combined = '\n'.join(x for x in outputs if x).strip()
    if len(combined) < 80:
        return False, 'entrega_final_insuficiente'
    low = combined.casefold()
    if any(marker in low for marker in BAD_MARKERS):
        return False, 'entrega_contem_falha'
    return True, 'ok'
