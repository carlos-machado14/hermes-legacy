from __future__ import annotations

from day_overview import overview_range
from temporal_query import resolve_temporal_range


def safe_read_fallback(text: str) -> str | None:
    """Resiliência local estritamente read-only para consultas temporais.

    Esta camada não decide intenção por palavras-chave e nunca executa mutações.
    Ela só responde quando existe uma referência temporal objetiva que pode ser
    resolvida localmente. Como o caminho é somente leitura, não dependemos de um
    caractere '?' para distinguir pergunta de comando: no pior caso o fallback
    apenas exibe o período citado e jamais altera agenda, tarefas ou rotinas.
    """
    raw = str(text or '').strip()
    if not raw:
        return None

    period = resolve_temporal_range(raw)
    if period is None:
        return None

    return overview_range(period.start, period.end, period.label)
