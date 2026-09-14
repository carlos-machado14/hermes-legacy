#!/usr/bin/env python3
from __future__ import annotations

import sys

import hermes_core
from connected_router import handle as handle_connected_command
from assistant_router import handle as handle_assistant_command
from context_builder import compact as compact_context
from contextual_router import handle as handle_contextual
from conversation_memory import add as remember_turn, compact as recent_conversation, recent as recent_items
from memory_router import handle as handle_memory_command
from memory_vault import append_daily, retrieve as retrieve_memory, sync_state_snapshots
from developer_router import handle as handle_developer_command
from mission_router import handle as handle_mission_command
from universal_router import handle as handle_universal_command
from domain_router import classify as classify_domain
from finance_router import handle as handle_finance_command
from semantic_intent_router import classify as classify_semantic_intent
from semantic_dispatcher import dispatch as dispatch_semantic_intent

_original_llm = hermes_core.llm


def _is_timeout_error(exc: Exception) -> bool:
    text = str(exc).casefold()
    return any(k in text for k in ('timed out', 'timeout', 'readtimeout', 'pooltimeout'))


def _retry_small(prompt: str, system: str) -> str | None:
    try:
        return _original_llm(
            prompt,
            system=system + (
                '\nResponda de forma curta e conclusiva. '
                'Se não tiver informação suficiente, diga exatamente qual dado falta. '
                'Não diga que está trabalhando, não prometa continuar em segundo plano e não invente fatos, comandos ou ferramentas.'
            ),
            max_tokens=180,
        )
    except Exception:
        return None


def _contextual_llm(prompt: str, system: str | None = None, max_tokens: int | None = None) -> str:
    context = compact_context(max_items=3)
    recent = recent_conversation(limit=4, max_chars=1600)
    sync_state_snapshots()
    long_term = retrieve_memory(prompt, limit=3, max_chars=1400)
    route = classify_domain(prompt)
    base_system = (
        'Você é Hermes, uma única inteligência artificial pessoal e geral. '
        'Você não é um agente de leads: negócios é apenas um dos seus domínios. '
        'Atue como assistente completo para vida pessoal, conhecimento, pesquisa, desenvolvimento, DevOps, negócios, finanças e comunicação. '
        'Use especialistas, memória, web, browser, rotinas e ferramentas locais como capacidades internas do mesmo Hermes. '
        'Quando não souber um fato, prefira pesquisar ou consultar uma fonte/ferramenta apropriada em vez de fingir que sabe. '
        'Nunca invente comandos slash, menus, ferramentas, integrações ou capacidades. Só mencione comandos/ferramentas que existam de verdade no contexto do Hermes. '
        'Se o usuário pedir para alterar o comportamento do próprio Hermes e você não tiver uma ferramenta válida para executar, diga objetivamente que não conseguiu aplicar; não ofereça recursos fictícios. '
        'Nunca diga que está trabalhando em segundo plano, que vai continuar automaticamente ou que o usuário precisa esperar, a menos que exista uma missão durável real já criada e identificável. '
        'Dados financeiros estruturados locais, quando existentes, são a fonte de verdade para gastos recorrentes; atualizações explícitas do usuário devem ser persistidas pelo roteador financeiro antes do LLM. '
        'Comandos de rotina, cron e briefing devem ser executados diretamente pelo gerenciador local quando puderem ser resolvidos deterministicamente, sem transformar uma alteração simples em missão longa. '
        'Quando houver identidade delegada, ferramentas conectadas como agenda, e-mail, GitHub e comunicação são executadas pelo Freud no contexto autenticado do usuário. '
        'Credenciais de usuário nunca pertencem ao Hermes e nunca devem ser solicitadas pelo modelo quando o Freud puder fornecer uma integração. '
        'Ações externas ou sensíveis devem respeitar aprovação e você nunca deve alegar que executou algo sem evidência. '
    )
    if system:
        base_system += '\n' + system
    enriched = (
        f"ROTEAMENTO\nDomínio principal: {route['primary_domain']} | agente: {route['agent']} | secundários: {', '.join(route['secondary_domains']) or 'nenhum'}\n\n"
        f"{context}\n\n"
        f"CONVERSA RECENTE\n{recent}\n\n"
        f"MEMÓRIA RELEVANTE\n{long_term or 'Nenhuma memória adicional relevante.'}\n\n"
        f"MENSAGEM ATUAL\n{prompt}\n\n"
        'Continue o assunto sem pedir novamente dados já disponíveis. Seja direto, útil e orientado a conclusão. '
        'Se faltar informação, informe objetivamente o que falta. '
        'Não invente comandos, ferramentas ou recursos para parecer útil. '
        'Nunca encerre a resposta no meio de uma frase ou item; conclua o raciocínio.'
    )
    low = prompt.lower()
    requested = max_tokens
    if requested is None:
        requested = 520 if any(k in low for k in ('detalhadamente', 'completo', 'completa', 'passo a passo', 'aprofund')) else 320
    try:
        return _original_llm(enriched, system=base_system, max_tokens=requested)
    except Exception as exc:
        if not _is_timeout_error(exc):
            raise
        retry = _retry_small(enriched, base_system)
        if retry:
            return retry
        return 'Não consegui obter uma resposta confiável para isso agora.'


hermes_core.llm = _contextual_llm


def _web_reply(text: str) -> str | None:
    try:
        from web_router import handle
        return handle(text)
    except ImportError:
        return None


def _cron_management_reply(text: str) -> str | None:
    low = text.casefold()
    routine_terms = ('rotina', 'rotinas', 'cron', 'crons', 'lembrete', 'lembretes', 'job', 'jobs', 'brief', 'briefing')
    if not any(k in low for k in routine_terms):
        return None
    action_terms = (
        'devia', 'deveria', 'rodou', 'executou', 'executada', 'executado', 'não veio', 'nao veio',
        'não rodou', 'nao rodou', 'cadê', 'cade', 'status', 'horário', 'horario', 'que horas',
        'atualiza', 'atualizar', 'melhora', 'melhorar', 'ajusta', 'ajustar', 'muda', 'mudar',
        'configure', 'configurar', 'crie', 'criar', 'adicione', 'adicionar', 'agende', 'agendar',
        'pause', 'pausar', 'pare', 'parar', 'retome', 'retomar', 'remova', 'remover', 'apague',
        'apagar', 'rode', 'rodar', 'execute', 'executar', 'liste', 'listar', 'quais', 'minhas',
    )
    if not any(k in low for k in action_terms):
        return None
    try:
        from cron_manager import handle
        return handle(text)
    except Exception:
        return None


def _brief_followup_reply(text: str) -> str | None:
    low = text.casefold().strip()
    detail_hints = (
        'mais detalhe', 'mais detalhes', 'mais detalhado', 'mais detalhada',
        'mais completo', 'mais completa', 'aprofund', 'melhor explicado',
        'quero assim', 'pode fazer', 'sim quero', 'sim, quero',
    )
    if not any(k in low for k in detail_hints):
        return None

    previous_user = ''
    for row in reversed(recent_items(limit=8)):
        if row.get('role') == 'user':
            previous_user = str(row.get('text') or '')
            break
    previous_low = previous_user.casefold()
    topic_hints = ('rotina', 'rotinas', 'brief', 'briefing', 'resumo', 'resumos', 'notícia', 'noticia', 'tópico', 'topico')
    if not previous_user or not any(k in previous_low for k in topic_hints):
        return None

    try:
        from cron_manager import update_brief_preferences
        synthetic = (
            'atualizar rotinas e briefings: quero resumo de cada tópico mais detalhado e mais completo, '
            'com contexto suficiente para entender sem abrir o link. ' + text
        )
        return update_brief_preferences(synthetic)
    except Exception:
        return None


def _semantic_reply(text: str) -> str | None:
    try:
        context = recent_conversation(limit=6, max_chars=1800)
        intent = classify_semantic_intent(text, context, _original_llm)
    except Exception:
        return None
    if not intent or float(intent.get('confidence') or 0.0) < 0.60:
        return None

    direct = dispatch_semantic_intent(text, intent)
    if direct is not None:
        return direct

    route = intent.get('route')
    try:
        if route == 'finance':
            return handle_finance_command(text)
        if route == 'connected':
            return handle_connected_command(text)
        if route == 'developer':
            return handle_developer_command(text)
        if route == 'memory':
            return handle_memory_command(text)
        if route == 'mission':
            return handle_mission_command(text)
        if route == 'research':
            return _web_reply(text)
        if route in {'assistant', 'devops'}:
            return handle_assistant_command(text) or handle_universal_command(text)
    except Exception:
        return None
    return None


def ask(text: str) -> str:
    text = text.strip()
    followup_reply = _brief_followup_reply(text)
    if followup_reply is not None:
        reply = followup_reply
    else:
        finance_reply = handle_finance_command(text)
        if finance_reply is not None:
            reply = finance_reply
        else:
            cron_reply = _cron_management_reply(text)
            if cron_reply is not None:
                reply = cron_reply
            else:
                semantic_reply = _semantic_reply(text)
                if semantic_reply is not None:
                    reply = semantic_reply
                else:
                    connected_reply = handle_connected_command(text)
                    if connected_reply is not None:
                        reply = connected_reply
                    else:
                        assistant_reply = handle_assistant_command(text)
                        if assistant_reply is not None:
                            reply = assistant_reply
                        else:
                            universal_reply = handle_universal_command(text)
                            if universal_reply is not None:
                                reply = universal_reply
                            else:
                                mission_reply = handle_mission_command(text)
                                if mission_reply is not None:
                                    reply = mission_reply
                                else:
                                    web_reply = _web_reply(text)
                                    if web_reply is not None:
                                        reply = web_reply
                                    else:
                                        developer_reply = handle_developer_command(text)
                                        if developer_reply is not None:
                                            reply = developer_reply
                                        else:
                                            memory_reply = handle_memory_command(text)
                                            if memory_reply is not None:
                                                reply = memory_reply
                                            else:
                                                contextual = handle_contextual(text)
                                                if contextual is not None:
                                                    reply = contextual
                                                else:
                                                    reply = hermes_core.ask(text)
    remember_turn('user', text)
    remember_turn('assistant', reply)
    append_daily('user', text)
    append_daily('assistant', reply)
    return reply


def main() -> int:
    if len(sys.argv) < 2:
        print('Hermes Core v4.6 Semantic Intent Router + Independent Universal Assistant', flush=True)
        return 0
    try:
        print(ask(' '.join(sys.argv[1:])), flush=True)
        return 0
    except Exception as exc:
        if _is_timeout_error(exc):
            print('Não consegui obter uma resposta confiável dentro do limite local.', flush=True)
            return 0
        print(f'Não consegui concluir essa solicitação. Detalhe: {exc}', flush=True)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
