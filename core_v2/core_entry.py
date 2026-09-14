#!/usr/bin/env python3
from __future__ import annotations

import sys

import hermes_core
from connected_router import handle as handle_connected_command
from assistant_router import handle as handle_assistant_command
from context_builder import compact as compact_context
from contextual_router import handle as handle_contextual
from conversation_memory import add as remember_turn, compact as recent_conversation
from memory_router import handle as handle_memory_command
from memory_vault import append_daily, retrieve as retrieve_memory, sync_state_snapshots
from developer_router import handle as handle_developer_command
from mission_router import handle as handle_mission_command
from universal_router import handle as handle_universal_command
from domain_router import classify as classify_domain
from finance_router import handle as handle_finance_command

_original_llm = hermes_core.llm


def _is_timeout_error(exc: Exception) -> bool:
    text = str(exc).casefold()
    return any(k in text for k in ('timed out', 'timeout', 'readtimeout', 'pooltimeout'))


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
        'Use especialistas e ferramentas como capacidades internas do mesmo Hermes. '
        'Dados financeiros estruturados locais, quando existentes, são a fonte de verdade para gastos recorrentes; atualizações explícitas do usuário devem ser persistidas pelo roteador financeiro antes do LLM. '
        'Comandos de rotina, cron e briefing devem ser executados diretamente pelo gerenciador local quando puderem ser resolvidos deterministicamente, sem transformar uma alteração simples em missão longa. '
        'Quando houver identidade delegada, ferramentas conectadas como agenda, e-mail, GitHub e comunicação são executadas pelo Freud no contexto autenticado do usuário. '
        'Credenciais de usuário nunca pertencem ao Hermes e nunca devem ser solicitadas pelo modelo quando o Freud puder fornecer uma integração. '
        'Ações externas ou sensíveis devem respeitar aprovação e você nunca deve alegar que executou algo sem evidência. '
        'Para tarefas realmente longas, continue sozinho por meio do runtime durável até concluir ou encontrar bloqueio real. '
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
        'Quando a tarefa exigir execução longa, prefira missão durável/checkpoints. '
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
        return (
            'Demorei mais do que deveria para gerar essa resposta. Mantive o contexto e sua mensagem registrada. '
            'Se a tarefa for longa, posso executá-la como missão durável sem perder o progresso.'
        )


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


def ask(text: str) -> str:
    text = text.strip()
    finance_reply = handle_finance_command(text)
    if finance_reply is not None:
        reply = finance_reply
    else:
        cron_reply = _cron_management_reply(text)
        if cron_reply is not None:
            reply = cron_reply
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
        print('Hermes Core v4.5 Independent Universal Assistant + Durable Missions + Web + Memory', flush=True)
        return 0
    try:
        print(ask(' '.join(sys.argv[1:])), flush=True)
        return 0
    except Exception as exc:
        if _is_timeout_error(exc):
            print('Demorei mais do que deveria para responder, mas mantive o contexto. Sua mensagem não foi perdida.', flush=True)
            return 0
        print(f'Não consegui concluir essa resposta agora, mas o contexto foi preservado. Detalhe: {exc}', flush=True)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
