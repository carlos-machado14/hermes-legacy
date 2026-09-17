from __future__ import annotations

import re

from day_overview import overview_range
from temporal_parser import norm
from temporal_query import resolve_temporal_range


_INTERROGATIVES = {
    'qual', 'quais', 'que', 'quando', 'onde', 'quanto', 'quantos', 'quantas',
    'como', 'quem', 'oq', 'o',
}


def _looks_read_only(raw: str) -> bool:
    """Reconhece forma interrogativa/consultiva, não a intenção de domínio.

    Esta é uma barreira de segurança para o fallback: quando o brain estiver fora,
    uma frase imperativa nunca deve virar uma simples listagem que parece ter atendido
    ao comando. Não há frases de negócio aqui; apenas sinais gramaticais genéricos.
    """
    if '?' in raw:
        return True
    text = norm(raw).strip()
    if not text:
        return False
    words = re.findall(r'[a-z0-9]+', text)
    if not words:
        return False
    if words[0] in _INTERROGATIVES:
        return True
    # Consultas nominais curtas como "agenda - semana que vem" não possuem verbo.
    # Limitamos a poucos tokens para não transformar comandos completos em leitura.
    return len(words) <= 4 and bool(re.search(r'[-–—:]', raw))


def safe_read_fallback(text: str) -> str | None:
    """Resiliência local estritamente read-only para consultas temporais.

    Só responde quando a mensagem tem forma de consulta e a referência temporal é
    objetiva. Se o brain falhar durante uma ação, este caminho retorna None e jamais
    mascara a ação exibindo uma agenda como se ela tivesse sido executada.
    """
    raw = str(text or '').strip()
    if not raw or not _looks_read_only(raw):
        return None

    period = resolve_temporal_range(raw)
    if period is None:
        return None

    return overview_range(period.start, period.end, period.label)
