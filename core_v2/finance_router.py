#!/usr/bin/env python3
from __future__ import annotations

import re

from finance_manager import (
    PROFILE,
    add_item,
    deactivate_item,
    reactivate_item,
    set_income,
    set_item_value,
    summary,
)

MONEY = r'(?:R\$\s*)?(\d{1,6}(?:[\.\,]\d{1,2})?)'


def _parse_money(raw: str) -> float | None:
    raw = str(raw or '').strip().replace('R$', '').replace(' ', '')
    try:
        if ',' in raw:
            raw = raw.replace('.', '').replace(',', '.')
        return float(raw)
    except Exception:
        return None


def _extract_last_money(text: str) -> float | None:
    vals = re.findall(MONEY, text, flags=re.I)
    if not vals:
        return None
    return _parse_money(vals[-1])


def _clean_added_name(text: str, kind: str) -> str:
    low = text
    # remove verbo + artigo/tipo
    low = re.sub(r'^\s*(?:adicione|adicionar|inclua|incluir|coloque|registr[ea]|nova|novo)\s+', '', low, flags=re.I)
    if kind == 'subscription':
        low = re.sub(r'^\s*(?:uma\s+)?assinatura\s+(?:de\s+)?', '', low, flags=re.I)
    else:
        low = re.sub(r'^\s*(?:um|uma)?\s*(?:gasto|despesa|conta)\s+(?:mensal\s+)?(?:de\s+)?', '', low, flags=re.I)
    # corta antes do valor
    low = re.split(r'\s+(?:de|por|no valor de|custando|custa)\s+R?\$?\s*\d', low, maxsplit=1, flags=re.I)[0]
    return low.strip(' .,-:')


def handle(text: str) -> str | None:
    raw = (text or '').strip()
    if not raw:
        return None
    low = raw.casefold()

    finance_terms = ('finance', 'financeiro', 'gasto', 'gastos', 'conta', 'contas', 'assinatura', 'assinaturas', 'salário', 'salario', 'renda')
    summary_terms = ('quanto gasto', 'quanto eu gasto', 'resumo financeiro', 'meus gastos', 'minhas contas', 'meu financeiro', 'situação financeira', 'situacao financeira')
    if any(k in low for k in summary_terms):
        if not PROFILE.exists():
            return 'Ainda não existe um perfil financeiro estruturado local. Importe seus dados uma vez e depois posso mantê-los por conversa.'
        return summary()

    # Renda/salário: exige palavra explícita + valor.
    if any(k in low for k in ('salário', 'salario', 'renda')) and any(k in low for k in ('agora', 'é ', 'e ', 'passou', 'foi para', 'atualize', 'atualiza')):
        value = _extract_last_money(raw)
        if value is not None:
            return set_income(value, source_text=raw)

    # Encerrar/quitar/cancelar uma conta existente.
    deactivate_words = ('terminei de pagar', 'quitei', 'cancelei', 'cancelar', 'cancele', 'remova', 'remover', 'não pago mais', 'nao pago mais', 'encerrei')
    if any(k in low for k in deactivate_words):
        if not PROFILE.exists():
            return None
        reply = deactivate_item(raw)
        if reply is not None:
            return reply

    # Reativar.
    if any(k in low for k in ('reative', 'reativar', 'voltei a pagar', 'ative novamente', 'ativar novamente')):
        if not PROFILE.exists():
            return None
        reply = reactivate_item(raw)
        if reply is not None:
            return reply

    # Adicionar nova assinatura/gasto mensal.
    add_words = ('adicione', 'adicionar', 'inclua', 'incluir', 'coloque', 'registre', 'registrar', 'nova assinatura', 'novo gasto', 'nova conta')
    if any(k in low for k in add_words):
        value = _extract_last_money(raw)
        if value is None:
            return None
        kind = 'subscription' if 'assinatura' in low else 'expense'
        name = _clean_added_name(raw, kind)
        if name:
            return add_item(name, value, kind=kind)

    # Alterar valor de item existente: só age se houver perfil + valor + linguagem de alteração.
    update_words = ('agora é', 'agora e', 'foi para', 'passou para', 'mudou para', 'atualize', 'atualiza', 'corrija para', 'corrige para', 'está em', 'esta em')
    if PROFILE.exists() and any(k in low for k in update_words):
        value = _extract_last_money(raw)
        if value is not None:
            reply = set_item_value(raw, value)
            if reply is not None:
                return reply

    # Não sequestra conversa financeira genérica; deixa o Hermes normal responder.
    if any(k in low for k in finance_terms):
        return None
    return None
