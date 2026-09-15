from __future__ import annotations

from assistant_os import attention, brief
from resource_manager import snapshot as resource_snapshot
from time_router import handle as handle_time


def handle(text: str) -> str | None:
    temporal = handle_time(text)
    if temporal is not None:
        return temporal

    low = text.strip().casefold()
    if low in {
        'meu dia','como está meu dia','como esta meu dia','panorama','panorama geral',
        'briefing','briefing geral','status assistente','status do assistente','status hermes',
    }:
        return brief()
    if low in {
        'o que precisa da minha atenção','o que precisa da minha atencao','o que requer minha atenção',
        'o que requer minha atencao','tem algo importante','o que é prioridade','o que e prioridade',
    }:
        return attention()
    if low in {'recursos','status recursos','status da vps','uso da vps'}:
        r = resource_snapshot()
        return (
            f"Recursos locais: CPU {r['cpu_percent']}% | RAM {r['memory_percent']}% | "
            f"livre {r['memory_available_mb']} MB | load {r['load_1m']}"
        )
    return None
