from __future__ import annotations

from day_overview import overview_range
from temporal_query import resolve_temporal_range


def safe_read_fallback(text: str) -> str | None:
    """Resiliência local estritamente read-only para consultas temporais.

    Esta camada não decide intenção por palavras-chave e nunca executa mutações.
    Ela só responde quando há uma pergunta explícita e uma referência temporal
    objetiva que pode ser resolvida localmente.
    """
    raw = str(text or '').strip()
    if not raw or '?' not in raw:
        return None

    period = resolve_temporal_range(raw)
    if period is None:
        return None

    return overview_range(period.start, period.end, period.label)
