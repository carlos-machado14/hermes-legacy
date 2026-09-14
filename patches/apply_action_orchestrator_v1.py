#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

CORE = Path.home() / '.hermes' / 'core-v2' / 'core_entry.py'
FASTPATH = Path.home() / '.hermes' / 'plugins' / 'hermes-core-fastpath' / '__init__.py'

CORE_MARKER = '# HERMES_ACTION_ORCHESTRATOR_V1'
FASTPATH_MARKER = '# HERMES_CHAT_CONTEXT_ENV_V1'


def patch_core() -> None:
    text = CORE.read_text(encoding='utf-8')
    if CORE_MARKER in text:
        print('[skip] core_entry.py action orchestrator already wired')
        return

    import_anchor = 'from universal_router import handle as handle_universal_command\n'
    import_line = 'from action_orchestrator import handle as handle_action_orchestrator\n'
    if import_line not in text:
        if import_anchor not in text:
            raise RuntimeError('core_entry import anchor not found')
        text = text.replace(import_anchor, import_anchor + import_line, 1)

    marker_anchor = '_original_llm = hermes_core.llm\n'
    if marker_anchor not in text:
        raise RuntimeError('core_entry marker anchor not found')
    text = text.replace(marker_anchor, marker_anchor + '\n' + CORE_MARKER + '\n', 1)

    target = "    direct_literal = _deterministic_reply(text)\n    if direct_literal is not None:\n        reply = direct_literal\n        route_name = 'deterministic_literal'\n    else:\n        followup_reply = _brief_followup_reply(text)\n"
    replacement = "    direct_literal = _deterministic_reply(text)\n    if direct_literal is not None:\n        reply = direct_literal\n        route_name = 'deterministic_literal'\n    else:\n        orchestrated = handle_action_orchestrator(text, llm=lambda p: _original_llm(p, system='Você é o planejador seguro de ações do Hermes. Responda em português do Brasil.', max_tokens=320))\n        if orchestrated is not None:\n            reply = orchestrated\n            route_name = 'action_orchestrator'\n        else:\n            followup_reply = _brief_followup_reply(text)\n"
    if target not in text:
        raise RuntimeError('ask() routing anchor not found in core_entry.py')
    text = text.replace(target, replacement, 1)

    # Reindent the existing branch that follows followup_reply because it is now nested one level deeper.
    start = text.index("            followup_reply = _brief_followup_reply(text)\n")
    end_marker = "\n\n    _persist_turn(text, reply)\n"
    end = text.index(end_marker, start)
    block = text[start:end]
    lines = block.splitlines(True)
    fixed = []
    first = True
    for line in lines:
        if first:
            fixed.append(line)
            first = False
        else:
            fixed.append('    ' + line if line.strip() else line)
    text = text[:start] + ''.join(fixed) + text[end:]

    CORE.write_text(text, encoding='utf-8')
    print('[ok] core_entry.py wired to universal action orchestrator')


def patch_fastpath() -> None:
    text = FASTPATH.read_text(encoding='utf-8')
    if FASTPATH_MARKER in text:
        print('[skip] fastpath chat context env already wired')
        return

    anchor = "    env['HERMES_TRACE_ID'] = trace\n"
    replacement = (
        "    env['HERMES_TRACE_ID'] = trace\n"
        "    # HERMES_CHAT_CONTEXT_ENV_V1\n"
        "    env['HERMES_CHAT_KEY'] = key or 'default'\n"
    )
    if anchor not in text:
        raise RuntimeError('fastpath env anchor not found')
    text = text.replace(anchor, replacement, 1)
    FASTPATH.write_text(text, encoding='utf-8')
    print('[ok] fastpath now passes chat identity to Core')


def main() -> int:
    for path in (CORE, FASTPATH):
        if not path.exists():
            raise SystemExit(f'missing runtime file: {path}')
    patch_core()
    patch_fastpath()
    print('OK: universal action orchestration wired')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
