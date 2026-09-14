from __future__ import annotations

import json
import re
from typing import Any

import hermes_core


def _fallback_plan(request: str) -> list[dict[str, Any]]:
    low = request.casefold()
    steps: list[dict[str, Any]] = []
    if any(k in low for k in ('pesquis', 'colet', 'empresa', 'lead', 'site', 'dentista', 'clínica', 'clinica')):
        steps.append({'title':'Pesquisar fontes reais na web','instruction':f'Pesquise dados públicos reais para: {request}','validator':'evidence','tool':'web_research'})
    if any(k in low for k in ('site', 'landing', 'demo', 'página', 'pagina')):
        steps.append({'title':'Auditar presença digital encontrada','instruction':f'Analise tecnicamente os sites encontrados relacionados a: {request}','validator':'evidence','tool':'site_audit'})
        steps.append({'title':'Analisar presença digital e requisitos','instruction':f'Analise necessidades, problemas e requisitos relacionados a: {request}','validator':'quality','tool':'llm'})
        steps.append({'title':'Produzir a entrega principal','instruction':f'Produza a entrega principal solicitada, de forma completa: {request}','validator':'quality','tool':'llm'})
    if not steps:
        steps = [
            {'title':'Entender e estruturar a solicitação','instruction':f'Analise a solicitação e determine a melhor forma de executá-la: {request}','validator':'quality','tool':'llm'},
            {'title':'Executar a tarefa','instruction':f'Execute integralmente esta solicitação: {request}','validator':'quality','tool':'llm'},
        ]
    steps.append({'title':'Validar resultado final','instruction':f'Confira se a solicitação original foi realmente concluída e corrija lacunas: {request}','validator':'final','tool':'llm'})
    return steps[:8]


def build_plan(request: str) -> list[dict[str, Any]]:
    system = (
        'Você é o planejador do Hermes. Transforme a missão em 2 a 8 etapas executáveis. '
        'Responda SOMENTE JSON válido no formato '
        '{"steps":[{"title":"...","instruction":"...","validator":"quality|evidence|final","tool":"llm|web_research|site_audit|site_crawl"}]}. '
        'Use web_research para pesquisa pública, site_audit para avaliar site e site_crawl para coletar páginas/contatos. '
        'Não inclua markdown. Não invente que ações externas já foram realizadas.'
    )
    prompt = f'Missão:\n{request}\n\nCrie um plano curto, sequencial, verificável e orientado à conclusão.'
    try:
        raw = hermes_core.llm(prompt, system=system, max_tokens=460)
        match = re.search(r'\{.*\}', raw, re.S)
        data = json.loads(match.group(0) if match else raw)
        steps = data.get('steps') if isinstance(data, dict) else None
        if isinstance(steps, list) and 1 <= len(steps) <= 8:
            clean = []
            for item in steps:
                if not isinstance(item, dict):
                    continue
                title = str(item.get('title') or '').strip()
                instruction = str(item.get('instruction') or '').strip()
                tool = str(item.get('tool') or 'llm').strip()
                if tool not in {'llm','web_research','site_audit','site_crawl'}:
                    tool = 'llm'
                if title and instruction:
                    clean.append({'title':title[:140],'instruction':instruction[:2500],'validator':str(item.get('validator') or 'quality'),'tool':tool})
            if clean:
                return clean
    except Exception:
        pass
    return _fallback_plan(request)
