#!/usr/bin/env python3
from __future__ import annotations

import json, re, time
from pathlib import Path
from typing import Any

from action_queue import add_action, approve, get_action, list_actions, summary as actions_summary, update_action
from autonomy_settings import load as load_settings
from context_builder import snapshot, primary_goal, ranked_tasks, best_opportunity
from decision_log import record
from personal_memory import profile
from research_engine import format_results
from task_manager import update_task, list_tasks

STATE_DIR = Path.home() / '.hermes/core-v2/state'
RESULTS_DIR = STATE_DIR / 'execution_results'

EXTERNAL_WORDS = ('enviar','mande','mandar','publicar','postar','contatar','contactar','ligar','comprar','pagar','vender','fechar negócio','fechar negocio','deletar','apagar','reiniciar','deploy','executar comando')
RESEARCH_WORDS = ('pesquisar','pesquise','buscar','encontrar','mapear','levantar','procurar','coletar dados')
DRAFT_WORDS = ('proposta','rascunho','copy','mensagem','oferta','roteiro','script','abordagem')
ANALYSIS_WORDS = ('analisar','comparar','priorizar','avaliar','organizar','planejar','definir','revisar','salvar empresa como lead','acompanhar resposta')


def classify_task(task: dict[str, Any]) -> dict[str, Any]:
    title = str(task.get('title') or '')
    low = title.casefold()
    metadata = task.get('metadata') or {}

    # O workflow diario de sites possui varias etapas internas seguras. Elas nao
    # devem pedir aprovacao uma a uma; somente contato/publicacao externa exige.
    if metadata.get('workflow') == 'daily_site_sales':
        step = int(metadata.get('step') or 0)
        if step == 9 or any(w in low for w in ('fazer contato', 'enviar ao cliente', 'publicar em produção', 'publicar em producao')):
            return {'kind':'external_action','risk':'medium','requires_approval':True}
        if step in {1, 2}:
            return {'kind':'research','risk':'low','requires_approval':False}
        if step in {3, 4, 6, 7, 10}:
            return {'kind':'analysis','risk':'low','requires_approval':False}
        if step in {5, 8}:
            return {'kind':'draft','risk':'low','requires_approval':False}

    if any(w in low for w in EXTERNAL_WORDS):
        return {'kind':'external_action','risk':'medium','requires_approval':True}
    if any(w in low for w in RESEARCH_WORDS):
        return {'kind':'research','risk':'low','requires_approval':False}
    if any(w in low for w in DRAFT_WORDS):
        return {'kind':'draft','risk':'low','requires_approval':False}
    if any(w in low for w in ANALYSIS_WORDS):
        return {'kind':'analysis','risk':'low','requires_approval':False}
    return {'kind':'user_action','risk':'medium','requires_approval':True}


def _already_queued(task_id: str) -> bool:
    return any(a.get('task_id') == task_id and a.get('status') not in {'done','failed','rejected'} for a in list_actions(None, 1000))


def propose_from_context(limit: int = 5) -> list[dict[str, Any]]:
    ctx = snapshot(); goal = primary_goal(ctx); tasks = ranked_tasks(ctx)
    created=[]
    for task in tasks:
        if len(created) >= limit: break
        tid = str(task.get('id') or '')
        if not tid or _already_queued(tid): continue
        c = classify_task(task)
        created.append(add_action(
            task.get('title',''), kind=c['kind'], task_id=tid,
            goal_id=(task.get('goal_id') or (goal or {}).get('id')),
            risk=c['risk'], requires_approval=c['requires_approval'],
            payload={'source':'task_manager'},
        ))
    return created


def release_safe_pending() -> dict[str, Any]:
    """Reclassifica acoes antigas que foram enfileiradas antes das regras atuais.

    Apenas acoes que hoje sao classificadas como low-risk internas sao liberadas.
    Acoes externas continuam pendentes de aprovacao explicita.
    """
    tasks = {str(t.get('id')): t for t in list_tasks()}
    released: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    for action in list_actions('pending_approval', 1000):
        task = tasks.get(str(action.get('task_id') or ''))
        if not task:
            kept.append(action)
            continue
        current = classify_task(task)
        if current.get('risk') == 'low' and not current.get('requires_approval'):
            action = update_action(
                action['id'],
                kind=current['kind'],
                risk='low',
                requires_approval=False,
                status='queued',
                reclassified_at=int(time.time()),
            )
            released.append(action)
        else:
            kept.append(action)
    return {'released': released, 'kept': kept}


def _save_result(action: dict[str, Any], text: str) -> str:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{action['id']}.txt"
    path.write_text(text, encoding='utf-8')
    return str(path)


def _draft(action: dict[str, Any]) -> str:
    p = profile(); skills=', '.join((p.get('skills') or [])[:8])
    opp = best_opportunity(snapshot())
    title = action.get('title','')
    lines=[f'Rascunho gerado para: {title}', '', 'Objetivo:', 'Criar uma versão inicial pronta para revisão antes de qualquer envio externo.', '']
    if opp: lines += [f'Oportunidade relacionada: {opp.get("title")}', '']
    if skills: lines += [f'Baseado nas habilidades registradas: {skills}', '']
    lines += ['Estrutura sugerida:', '- Problema observado', '- Resultado que podemos entregar', '- Escopo objetivo', '- Prazo estimado', '- Próximo passo / chamada para ação', '', 'Nenhum contato externo foi realizado.']
    return '\n'.join(lines)


def _analysis(action: dict[str, Any]) -> str:
    ctx=snapshot(); goal=primary_goal(ctx); opp=best_opportunity(ctx); tasks=ranked_tasks(ctx)
    out=[f'Análise concluída: {action.get("title")}']
    if goal: out.append(f"Objetivo principal: {goal.get('title')} | progresso={goal.get('progress',0)}%")
    if opp: out.append(f"Melhor oportunidade atual: {opp.get('title')} | score={opp.get('score',0)}/100")
    if tasks:
        out.append('Prioridades atuais:')
        for i,t in enumerate(tasks[:5],1): out.append(f"{i}. {t.get('title')}")
    out.append('Resultado salvo localmente; nenhuma ação externa foi executada.')
    return '\n'.join(out)


def execute_action(ref: str, *, force_approved: bool = False) -> dict[str, Any]:
    action=get_action(ref)
    if not action: raise KeyError(ref)
    if action.get('requires_approval') and action.get('status') != 'approved' and not force_approved:
        return action
    if action.get('status') in {'done','rejected'}: return action
    update_action(action['id'], status='running', started_at=int(time.time()))
    try:
        kind=action.get('kind')
        if kind == 'research':
            query = re.sub(r'^(pesquisar|pesquise|buscar|encontrar|mapear|levantar|procurar)\s+', '', action.get('title',''), flags=re.I).strip() or action.get('title','')
            result = format_results(query, limit=5)
        elif kind == 'draft': result = _draft(action)
        elif kind == 'analysis': result = _analysis(action)
        elif kind in {'external_action','user_action'}:
            result = 'Ação depende de você ou de autorização explícita. Nenhuma ação externa foi executada automaticamente.'
            return update_action(action['id'], status='blocked', result=result)
        else: result = _analysis(action)
        path=_save_result(action, result)
        done=update_action(action['id'], status='done', result=result, result_path=path, completed_at=int(time.time()))
        if action.get('task_id'):
            try: update_task(action['task_id'], status='done', completed_at=int(time.time()), metadata={'completed_by':'hermes-autonomy','action_id':action['id'],'result_path':path})
            except Exception: pass
        record('autonomous_action_completed', action.get('title',''), metadata={'action_id':action['id'],'kind':kind,'result_path':path})
        return done
    except Exception as exc:
        record('autonomous_action_failed', action.get('title',''), metadata={'action_id':action['id'],'error':str(exc)})
        return update_action(action['id'], status='failed', error=str(exc))


def approve_and_execute(ref: str) -> dict[str, Any]:
    action=approve(ref)
    return execute_action(action['id'])


def run_cycle() -> dict[str, Any]:
    settings=load_settings()
    if not settings.get('enabled'): return {'ok':False,'reason':'autonomy_disabled','executed':[],'waiting_approval':[]}
    release_safe_pending()
    propose_from_context(limit=max(2, int(settings.get('max_actions_per_cycle',2))*2))
    executed=[]; waiting=[]
    for action in list_actions(None, 100):
        if action.get('status') == 'pending_approval': waiting.append(action); continue
        if action.get('status') != 'queued': continue
        if len(executed) >= int(settings.get('max_actions_per_cycle',2)): break
        if action.get('risk') == 'low' and settings.get('auto_execute_low_risk'):
            executed.append(execute_action(action['id']))
        else: waiting.append(update_action(action['id'], status='pending_approval', requires_approval=True))
    return {'ok':True,'executed':executed,'waiting_approval':waiting}


def capability_summary() -> str:
    return (
        'O que posso executar sozinho agora:\n'
        '- pesquisas web simples\n- análises e priorização\n- organização de contexto\n- rascunhos de proposta/oferta/mensagem\n- planejamento interno\n- etapas internas do workflow diário de sites\n\n'
        'O que exige sua aprovação:\n- contato com pessoas/clientes\n- publicação/envio externo\n- compras/pagamentos\n- deploy/restart/delete\n- push/PR/merge quando configurado como ação externa\n- outras ações com efeito externo relevante\n\n'
        'Assim eu avanço sozinho no trabalho interno e só interrompo você quando existe efeito externo real.'
    )


def summary() -> str:
    return actions_summary()
