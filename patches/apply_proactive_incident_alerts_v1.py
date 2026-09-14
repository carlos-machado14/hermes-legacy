#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

TARGET = Path.home() / '.hermes' / 'core-v2' / 'autonomous_service.py'
MARKER = '# HERMES_PROACTIVE_INCIDENT_ALERTS_V1'


def main() -> int:
    text = TARGET.read_text(encoding='utf-8')
    if MARKER in text:
        print('[skip] proactive incident alerts already active')
        return 0

    import_anchor = 'from task_manager import list_tasks\n'
    if import_anchor not in text:
        raise RuntimeError('autonomous_service import anchor not found')
    text = text.replace(import_anchor, import_anchor + 'from incident_store import recent_incidents\n', 1)

    helper_anchor = '\ndef _autonomy_cycle(runtime: dict[str, Any], now: datetime) -> bool:\n'
    helper = r'''

# HERMES_PROACTIVE_INCIDENT_ALERTS_V1
def _send_new_incidents(runtime: dict[str, Any]) -> bool:
    last_ts = int(runtime.get('last_incident_alert_ts') or 0)
    rows = [row for row in recent_incidents(limit=50, status='open') if int(row.get('ts') or 0) > last_ts]
    rows = [row for row in rows if str(row.get('severity') or '').lower() in {'warning', 'critical'}]
    if not rows:
        return False
    rows.sort(key=lambda row: int(row.get('ts') or 0))
    selected = rows[-5:]
    lines = ['🚨 Hermes — detectei um problema que merece sua atenção:']
    for row in selected:
        severity = str(row.get('severity') or 'warning').upper()
        lines.append(f"- [{severity}] {row.get('summary')}")
        details = row.get('details') if isinstance(row.get('details'), dict) else {}
        target = details.get('target') or details.get('project')
        detail = details.get('detail')
        if target:
            lines.append(f"  Alvo: {target}")
        if detail:
            lines.append(f"  Detalhe: {str(detail)[:500]}")
    lines.append('\nPosso te ajudar a diagnosticar e montar o plano de correção.')
    if not _send('\n'.join(lines)):
        return False
    runtime['last_incident_alert_ts'] = max(int(row.get('ts') or 0) for row in rows)
    runtime['updated_at'] = int(time.time())
    _write_json(RUNTIME_FILE, runtime)
    record('proactive_incident', f'{len(rows)} incidente(s) novo(s) avisado(s).')
    return True
'''
    if helper_anchor not in text:
        raise RuntimeError('autonomous_service helper anchor not found')
    text = text.replace(helper_anchor, helper + helper_anchor, 1)

    tick_anchor = "    now = datetime.now(); runtime = _read_json(RUNTIME_FILE, {})\n"
    tick_replacement = (
        "    now = datetime.now(); runtime = _read_json(RUNTIME_FILE, {})\n"
        "    if not _quiet(proactive, now) and _send_new_incidents(runtime):\n"
        "        return\n"
    )
    if tick_anchor not in text:
        raise RuntimeError('autonomous_service tick anchor not found')
    text = text.replace(tick_anchor, tick_replacement, 1)

    TARGET.write_text(text, encoding='utf-8')
    print('OK: proactive watcher incidents will be surfaced on Telegram')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
