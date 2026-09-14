#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path.home() / '.hermes' / 'core-v2'
WEB = ROOT / 'web_router.py'
SEMANTIC = ROOT / 'semantic_intent_router.py'
CRON = ROOT / 'cron_manager.py'

WEB_MARKER = '# HERMES_ONEOFF_RESEARCH_ROUTING_V1'
SEMANTIC_MARKER = '# HERMES_CRON_INTENT_GUARD_V1'
CRON_MARKER = '# HERMES_CRON_QUERY_GUARD_V1'


def append_or_insert_before_main(path: Path, marker: str, block: str) -> None:
    text = path.read_text(encoding='utf-8')
    if marker in text:
        print(f'[skip] {path.name}: already patched')
        return
    needle = "\nif __name__ == '__main__':\n"
    rendered = '\n' + block.rstrip() + '\n'
    if needle in text:
        text = text.replace(needle, rendered + needle, 1)
    else:
        text = text.rstrip() + rendered + '\n'
    path.write_text(text, encoding='utf-8')
    print(f'[ok] {path.name}')


def patch_web() -> None:
    block = r'''
# HERMES_ONEOFF_RESEARCH_ROUTING_V1
_ONEOFF_COMPANY_ACTIONS = (
    'coleta', 'coletar', 'colete', 'levante', 'levantar', 'ache', 'achar',
    'encontre', 'encontrar', 'busque', 'buscar', 'procure', 'procurar',
    'pesquise', 'pesquisar', 'identifique', 'identificar',
)
_ONEOFF_COMPANY_HINTS = (
    'empresa', 'empresas', 'negocio', 'negócio', 'comercio', 'comércio',
    'clinica', 'clínica', 'dentista', 'advogado', 'restaurante', 'loja',
)


def _looks_like_oneoff_company_research(text: str) -> bool:
    low = str(text or '').casefold()
    has_entity = any(k in low for k in _ONEOFF_COMPANY_HINTS)
    has_action = any(k in low for k in _ONEOFF_COMPANY_ACTIONS)
    sales_fit = any(k in low for k in ('sem site', 'não tenha site', 'nao tenha site', 'precisa de site', 'ter um site'))
    return has_entity and (has_action or sales_fit)


_handle_before_oneoff_research = handle


def handle(text: str) -> str | None:
    raw = str(text or '').strip()
    if _looks_like_oneoff_company_research(raw):
        try:
            return format_research(research_company(raw, limit=5))
        except Exception as exc:
            return f'Não consegui concluir a pesquisa real agora. Detalhe: {exc}'
    return _handle_before_oneoff_research(raw)
'''
    append_or_insert_before_main(WEB, WEB_MARKER, block)


def patch_semantic() -> None:
    block = r'''
# HERMES_CRON_INTENT_GUARD_V1
_CRON_CREATE_WORDS = (
    'crie', 'criar', 'quero criar', 'vamos criar', 'nova rotina', 'quero uma rotina',
    'adicione', 'adicionar', 'agende', 'agendar', 'me lembre', 'lembre-me',
)
_CRON_EXISTENCE_QUESTIONS = (
    'ja temos', 'já temos', 'temos uma rotina', 'tem uma rotina', 'existe uma rotina',
    'ja existe', 'já existe', 'qual rotina', 'quais rotinas', 'minhas rotinas',
)


def _explicit_cron_create(text: str) -> bool:
    low = _norm(text)
    return any(k in low for k in _CRON_CREATE_WORDS)


def _cron_existence_question(text: str) -> bool:
    low = _norm(text)
    return any(k in low for k in _CRON_EXISTENCE_QUESTIONS)


_classify_before_cron_guard = classify


def classify(text: str, recent_context: str, llm: Callable[..., str]) -> dict[str, Any] | None:
    result = _classify_before_cron_guard(text, recent_context, llm)
    if not isinstance(result, dict) or result.get('route') != 'cron':
        return result

    action = str(result.get('action') or '')
    if _cron_existence_question(text):
        guarded = dict(result)
        guarded['action'] = 'list'
        guarded['reason'] = 'pergunta sobre existência/listagem de rotina; criação bloqueada'
        return guarded

    if action == 'create' and not _explicit_cron_create(text):
        return None
    return result
'''
    append_or_insert_before_main(SEMANTIC, SEMANTIC_MARKER, block)


def patch_cron() -> None:
    block = r'''
# HERMES_CRON_QUERY_GUARD_V1
_CRON_EXISTENCE_QUESTIONS_V1 = (
    'ja temos', 'já temos', 'temos uma rotina', 'tem uma rotina', 'existe uma rotina',
    'ja existe', 'já existe', 'qual rotina', 'quais rotinas', 'minhas rotinas',
)


_handle_before_query_guard = handle


def handle(text: str, *args, **kwargs) -> str:
    low = norm(text)
    if any(k in low for k in _CRON_EXISTENCE_QUESTIONS_V1):
        return _status_report()
    return _handle_before_query_guard(text, *args, **kwargs)
'''
    append_or_insert_before_main(CRON, CRON_MARKER, block)


def main() -> int:
    for path in (WEB, SEMANTIC, CRON):
        if not path.exists():
            raise SystemExit(f'missing runtime file: {path}')
    patch_web()
    patch_semantic()
    patch_cron()
    print('OK: one-off research routing + cron false-positive guards applied')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
