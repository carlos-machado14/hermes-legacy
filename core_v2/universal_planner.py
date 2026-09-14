from __future__ import annotations

import json
import re
from typing import Any

import hermes_core
from domain_router import classify


def _fallback(text: str) -> dict[str, Any]:
    route = classify(text)
    primary = route['primary_domain']
    steps = [
        {'title':'Entender contexto e Definition of Done','domain':primary,'instruction':f'Defina o que precisa ser verdade para considerar concluído: {text}','validator':'quality'},
        {'title':'Executar a solicitação','domain':primary,'instruction':f'Execute a solicitação usando as ferramentas disponíveis e contexto persistente: {text}','validator':'evidence'},
        {'title':'Revisar e concluir','domain':'control','instruction':'Valide se o pedido original foi concluído, corrija lacunas e só então encerre.','validator':'final'},
    ]
    return {'route': route, 'steps': steps, 'definition_of_done':['Pedido original atendido','Resultado validado','Nenhuma ação externa alegada sem evidência']}


def build(text: str) -> dict[str, Any]:
    route = classify(text)
    system = (
        'Você é o Universal Planner do Hermes. Planeje qualquer tipo de missão, não apenas negócios. '
        'Domínios válidos: personal, knowledge, research, developer, devops, business, finance, communication, control. '
        'Responda SOMENTE JSON válido com route, definition_of_done e steps. Cada step deve ter title, domain, instruction e validator. '
        'Use no máximo 8 etapas. Ações externas/sensíveis devem ser claramente marcadas para aprovação e nunca presumidas como executadas.'
    )
    prompt = (
        f'Roteamento inicial: {json.dumps(route, ensure_ascii=False)}\n'
        f'Missão: {text}\n\n'
        'Monte um plano curto, verificável, multi-domínio quando necessário e orientado a conclusão real.'
    )
    try:
        raw = hermes_core.llm(prompt, system=system, max_tokens=650)
        match = re.search(r'\{.*\}', raw, re.S)
        data = json.loads(match.group(0) if match else raw)
        steps = data.get('steps') if isinstance(data, dict) else None
        if isinstance(steps, list) and steps:
            clean = []
            for step in steps[:8]:
                if not isinstance(step, dict):
                    continue
                title = str(step.get('title') or '').strip()
                instruction = str(step.get('instruction') or '').strip()
                domain = str(step.get('domain') or route['primary_domain']).strip()
                if title and instruction:
                    clean.append({
                        'title': title[:160],
                        'domain': domain,
                        'instruction': instruction[:3000],
                        'validator': str(step.get('validator') or 'quality'),
                        'requires_approval': bool(step.get('requires_approval', False)),
                    })
            if clean:
                return {
                    'route': data.get('route') or route,
                    'definition_of_done': data.get('definition_of_done') or ['Pedido concluído e validado'],
                    'steps': clean,
                }
    except Exception:
        pass
    return _fallback(text)
