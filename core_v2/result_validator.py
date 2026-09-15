from __future__ import annotations

import re
from typing import Any

BAD_MARKERS=(
    'não consegui','nao consegui','erro:','timed out','timeout','tente novamente','não foi possível','nao foi possivel',
    'nenhum dado foi inventado','sem encontrar um resultado verificável','sem encontrar um resultado verificavel',
)


def validate_step(step: dict[str, Any], output: str) -> tuple[bool,str]:
    text=(output or '').strip()
    if len(text)<20: return False,'resultado_curto_ou_vazio'
    low=text.casefold()
    if any(marker in low for marker in BAD_MARKERS): return False,'resultado_indica_falha'
    mode=str(step.get('validator') or 'quality')
    if mode=='evidence':
        has_signal=bool(re.search(r'https?://|\b(?:telefone|whatsapp|endereço|endereco|instagram|site|fonte|arquivo|commit|teste)\b',low))
        if not has_signal: return False,'faltam_evidencias_ou_dados_verificaveis'
    return True,'ok'


def validate_final(request: str, outputs: list[str]) -> tuple[bool,str]:
    combined='\n'.join(x for x in outputs if x).strip()
    if len(combined)<80: return False,'entrega_final_insuficiente'
    low=combined.casefold(); req=(request or '').casefold()
    if any(marker in low for marker in BAD_MARKERS): return False,'entrega_contem_falha'

    research = any(x in req for x in ('pesquise','pesquisar','encontre','buscar','busque','procure','investigue','lead','empresa','cliente'))
    if research and not re.search(r'https?://',combined,re.I):
        return False,'pesquisa_sem_fontes_verificaveis'

    company = any(x in req for x in ('empresa','cliente','lead','presença digital','presenca digital'))
    if company:
        if not any(x in low for x in ('melhor candidato','potencial comercial','lead score','empresa/página','empresa/pagina')):
            return False,'prospeccao_sem_candidato_qualificado'
        if any(x in req for x in ('contato','todos os dados','whatsapp','telefone')) and not any(x in low for x in ('contato','whatsapp','telefone')):
            return False,'prospeccao_sem_contato_verificado'

    if any(x in req for x in ('o melhor','melhor opção','melhor opcao')) and not any(x in low for x in ('melhor','recomendo','selecionado','candidato')):
        return False,'pedido_de_selecao_sem_escolha_final'
    return True,'ok'
