#!/usr/bin/env python3
from __future__ import annotations

from typing import Any


def _brief_update(intent: dict[str, Any]) -> str:
    from cron_manager import load_brief_prefs, save_brief_prefs

    params = intent.get('params') if isinstance(intent.get('params'), dict) else {}
    prefs = load_brief_prefs()
    changed: list[str] = []

    level = str(params.get('detail_level') or '').strip().lower()
    if level == 'detailed':
        prefs['detail_level'] = 'detailed'
        prefs['summary_chars'] = 900
        prefs['include_summary'] = True
        changed.append('resumos configurados no nível detalhado')
    elif level == 'short':
        prefs['detail_level'] = 'short'
        prefs['summary_chars'] = 300
        prefs['include_summary'] = True
        changed.append('resumos configurados no nível curto')
    elif level == 'normal':
        prefs['detail_level'] = 'normal'
        prefs['summary_chars'] = 520
        prefs['include_summary'] = True
        changed.append('resumos configurados no nível normal')

    if params.get('summary_without_link') is True:
        prefs['include_summary'] = True
        prefs['links_are_optional'] = True
        prefs['summary_chars'] = max(int(prefs.get('summary_chars') or 520), 700)
        changed.append('cada tópico terá contexto suficiente para ser entendido sem abrir o link')

    if isinstance(params.get('include_links'), bool):
        prefs['include_links'] = bool(params['include_links'])
        changed.append('links mantidos como fonte' if params['include_links'] else 'links ocultados')

    if not changed:
        # O classificador entendeu a intenção de alterar o briefing, mas não
        # conseguiu extrair uma preferência específica. O padrão útil é tornar
        # o conteúdo mais autoexplicativo, sem inventar outras opções.
        prefs['include_summary'] = True
        prefs['links_are_optional'] = True
        prefs['summary_chars'] = max(int(prefs.get('summary_chars') or 520), 700)
        changed.append('briefings configurados para trazer mais contexto diretamente no Telegram')

    save_brief_prefs(prefs)
    return (
        '✅ Atualizei o formato dos briefings pelo significado do seu pedido.\n- '
        + '\n- '.join(changed)
        + '\nOs horários e jobs não foram alterados.'
    )


def _cron_operation(intent: dict[str, Any]) -> str | None:
    from cron_manager import HERMES, _status_report, create_job, run

    action = str(intent.get('action') or 'unknown')
    text = str(intent.get('_text') or '')
    target = str(intent.get('target') or '').strip()

    if action == 'create':
        return create_job(text)
    if action in {'status', 'list'}:
        return _status_report()
    if action == 'update_brief':
        return _brief_update(intent)

    command_map = {
        'pause': ('pause', 'pausada'),
        'resume': ('resume', 'retomada'),
        'run': ('run', 'executada'),
        'remove': ('remove', 'removida'),
    }
    if action in command_map:
        if not target:
            return 'Entendi a ação na rotina, mas preciso do nome ou ID do job para executar com segurança.'
        command, label = command_map[action]
        code, out = run([HERMES, 'cron', command, target])
        if code != 0:
            return f"Não consegui alterar a rotina '{target}'. {out[-500:]}"
        return f'✅ Rotina {label}: {target}'
    return None


def dispatch(text: str, intent: dict[str, Any] | None) -> str | None:
    if not isinstance(intent, dict):
        return None
    if float(intent.get('confidence') or 0.0) < 0.60:
        return None
    enriched = dict(intent)
    enriched['_text'] = text
    if intent.get('route') == 'cron':
        return _cron_operation(enriched)
    return None
