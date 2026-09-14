from __future__ import annotations

import json
import re
from typing import Any

import hermes_core
from freud_broker_client import catalog, configured, execute, identity, link, status

CONNECTED_HINTS = (
    'agenda', 'calendário', 'calendario', 'evento', 'reunião', 'reuniao',
    'gmail', 'email', 'e-mail', 'caixa de entrada', 'inbox',
    'github', 'repositório', 'repositorio', 'repo', 'issue',
    'whatsapp', 'integrações', 'integracoes', 'conectado', 'conectadas',
    'o que precisa da minha atenção', 'o que precisa da minha atencao',
)


def _json_from_text(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.I)
    raw = re.sub(r'\s*```$', '', raw)
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except Exception:
        pass
    match = re.search(r'\{.*\}', raw, re.S)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _tool_specs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in items[:30]:
        fn = item.get('function') if isinstance(item, dict) else None
        if not isinstance(fn, dict):
            continue
        out.append({
            'name': fn.get('name'),
            'description': fn.get('description'),
            'parameters': fn.get('parameters'),
        })
    return out


def _decide(text: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
    prompt = (
        'Selecione no máximo UMA ferramenta Freud para atender a mensagem atual. '
        'Use somente os nomes fornecidos. Para panorama geral de agenda/e-mails/GitHub prefira assistant_overview. '
        'Operações externas podem retornar approvalRequired e isso é esperado. '
        'Responda SOMENTE JSON válido: {"name":"...","arguments":{...}} ou {"name":null,"arguments":{}}.\n\n'
        f'FERRAMENTAS: {json.dumps(_tool_specs(tools), ensure_ascii=False)[:14000]}\n\n'
        f'MENSAGEM: {text}'
    )
    raw = hermes_core.llm(
        prompt,
        system='Você é um roteador conservador de ferramentas conectadas. Retorne apenas JSON válido.',
        max_tokens=280,
    )
    return _json_from_text(raw) or {'name': None, 'arguments': {}}


def _summarize(text: str, tool_name: str, payload: dict[str, Any]) -> str:
    result = payload.get('result', payload)
    if isinstance(result, dict) and result.get('approvalRequired'):
        return (
            f"A ação foi preparada no Freud e precisa de aprovação explícita.\n"
            f"Aprovação: {result.get('approvalId')}\n"
            f"{result.get('description') or ''}".strip()
        )
    prompt = (
        f'PEDIDO DO USUÁRIO\n{text}\n\n'
        f'FERRAMENTA EXECUTADA\n{tool_name}\n\n'
        f'RESULTADO REAL DO FREUD\n{json.dumps(result, ensure_ascii=False)[:18000]}\n\n'
        'Responda em português, de forma direta. Use somente os dados do resultado real. '
        'Se uma integração não estiver disponível, diga isso claramente. Não invente dados.'
    )
    return hermes_core.llm(prompt, system='Você resume resultados reais de ferramentas conectadas.', max_tokens=520)


def handle(text: str) -> str | None:
    raw = text.strip()
    low = raw.casefold()

    match = re.fullmatch(r'conectar\s+freud\s+([a-f0-9]{8,20})', low, flags=re.I)
    if match:
        if not configured():
            s = status()
            return (
                'O broker Freud ainda não está configurado nesta VPS. '
                f"URL configurada: {s['brokerUrlConfigured']} | token configurado: {s['tokenConfigured']}"
            )
        result = link(match.group(1))
        if result.get('linked'):
            return 'Telegram vinculado ao seu usuário Freud. A partir de agora posso usar suas integrações conectadas sem receber suas credenciais.'
        return f"Não consegui vincular o Telegram ao Freud: {result.get('error') or result}"

    if low in {'status conectado', 'status freud', 'status do freud', 'integrações conectadas', 'integracoes conectadas'}:
        local = status()
        if not local['configured']:
            return (
                'Connected Assistant local ainda não configurado. '
                f"URL Freud: {local['brokerUrlConfigured']} | token: {local['tokenConfigured']} | canal: {local['channel'] or 'não identificado'}"
            )
        data = execute('connected_status', {})
        if not data.get('ok'):
            return f"Broker configurado, mas o canal ainda não está vinculado ou está indisponível: {data.get('error')}"
        return _summarize(raw, 'connected_status', data)

    if not configured() or not any(hint in low for hint in CONNECTED_HINTS):
        return None

    cat = catalog()
    if not cat.get('linked'):
        return None
    tools = list(cat.get('tools') or [])
    decision = _decide(raw, tools)
    name = str(decision.get('name') or '').strip()
    if not name:
        return None
    args = decision.get('arguments') if isinstance(decision.get('arguments'), dict) else {}
    result = execute(name, args)
    if not result.get('ok'):
        return f"Não consegui consultar o Freud agora: {result.get('error') or 'erro desconhecido'}"
    return _summarize(raw, name, result)
