#!/usr/bin/env python3
from __future__ import annotations

import re
from crm_engine import summary as crm_summary, hot_leads, followups_due
from lead_manager import add_lead, summary as leads_summary, update_lead
from opportunity_hunter import hunt_and_register
from deep_research import format_report
from learning_engine import record_outcome, summary as learning_summary
from decision_log import record


def _after(text: str, markers: tuple[str, ...]) -> str:
    low=text.lower()
    for marker in markers:
        i=low.find(marker)
        if i >= 0: return text[i+len(marker):].strip(' :,-')
    return ''


def handle(text: str) -> str | None:
    t=text.strip(); low=t.lower()
    if low in {'crm','meu crm','pipeline','pipeline de vendas','meus leads','listar leads'}:
        return crm_summary() if low not in {'meus leads','listar leads'} else leads_summary()
    if any(k in low for k in ('leads mais quentes','leads quentes','melhores leads')):
        rows=hot_leads(8)
        if not rows: return 'Nenhum lead qualificado ainda.'
        return 'Leads mais quentes:\n'+'\n'.join(f"- [{x['id']}] {x['name']} | score={x.get('score',0)} | {x.get('stage')}" for x in rows)
    if any(k in low for k in ('follow-up hoje','follow up hoje','quem precisa de follow-up','quem precisa de follow up')):
        rows=followups_due(10)
        if not rows: return 'Nenhum follow-up vencido agora.'
        return 'Follow-ups pendentes:\n'+'\n'.join(f"- [{x['id']}] {x['name']} | {x.get('next_followup_at')}" for x in rows)
    if low.startswith('adicione lead ') or low.startswith('crie lead '):
        name=_after(t,('adicione lead','crie lead'))
        lead=add_lead(name); record('lead_created',lead['name'],metadata={'lead_id':lead['id']})
        return f"Lead criado: [{lead['id']}] {lead['name']}"
    if low.startswith('mover lead ') and ' para ' in low:
        body=_after(t,('mover lead',)); ref,stage=re.split(r'\s+para\s+',body,maxsplit=1,flags=re.I)
        try:
            lead=update_lead(ref.strip(),stage=stage.strip().lower()); return f"Lead atualizado: {lead['name']} → {lead['stage']}"
        except KeyError: return 'Lead não encontrado.'
    if any(low.startswith(k) for k in ('encontre leads ', 'buscar leads ', 'caçar oportunidades ', 'cacar oportunidades ')):
        query=_after(t,('encontre leads','buscar leads','caçar oportunidades','cacar oportunidades'))
        return hunt_and_register(query)
    if any(low.startswith(k) for k in ('pesquisa profunda ', 'pesquise profundamente ', 'investigue ')):
        query=_after(t,('pesquisa profunda','pesquise profundamente','investigue'))
        return format_report(query)
    if low.startswith('resultado positivo '):
        label=_after(t,('resultado positivo',)); record_outcome('business',label,True); return f'Aprendizado registrado como positivo: {label}'
    if low.startswith('resultado negativo '):
        label=_after(t,('resultado negativo',)); record_outcome('business',label,False); return f'Aprendizado registrado como negativo: {label}'
    if any(k in low for k in ('o que você aprendeu','o que voce aprendeu','aprendizados do hermes','aprendizados de negócio','aprendizados de negocio')):
        return learning_summary()
    return None
