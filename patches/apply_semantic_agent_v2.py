#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path.home() / '.hermes' / 'core-v2'
CORE = ROOT / 'core_entry.py'
FAST = Path.home() / '.hermes' / 'plugins' / 'hermes-core-fastpath' / '__init__.py'
CORE_MARKER = '# HERMES_SEMANTIC_AGENT_V2'
FAST_MARKER = '# HERMES_SEMANTIC_AGENT_TIMEOUTS_V2'


def patch_core() -> None:
    text = CORE.read_text(encoding='utf-8')
    if CORE_MARKER in text:
        print('[skip] semantic agent v2 already active in core_entry.py')
        return

    import_anchor = 'from universal_router import handle as handle_universal_command\n'
    if import_anchor not in text:
        raise RuntimeError('core_entry import anchor not found')
    text = text.replace(
        import_anchor,
        import_anchor + 'from semantic_agent import handle as handle_semantic_agent\n' + CORE_MARKER + '\n',
        1,
    )

    # action_orchestrator_v1 is installed immediately before this patch. Nest the
    # entire compatibility routing chain under Semantic Agent V2 without depending
    # on every old router's exact indentation/content.
    action_line = "        orchestrated = handle_action_orchestrator(text, llm=lambda p: _original_llm(p, system='Você é o planejador seguro de ações do Hermes. Responda em português do Brasil.', max_tokens=320))\n"
    start = text.find(action_line)
    if start < 0:
        raise RuntimeError('action orchestrator routing anchor not found in core_entry.py')

    end_marker = "\n\n    _persist_turn(text, reply)\n"
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError('core_entry persist anchor not found')

    legacy_block = text[start:end]
    nested_legacy = ''.join(('    ' + line if line.strip() else line) for line in legacy_block.splitlines(True))
    semantic_block = (
        "        # Semantic Agent V2 is the primary brain. It understands the complete request,\n"
        "        # recent conversation and available capabilities before choosing tools.\n"
        "        semantic_agent_reply = handle_semantic_agent(text, _original_llm)\n"
        "        if semantic_agent_reply is not None:\n"
        "            reply = semantic_agent_reply\n"
        "            route_name = 'semantic_agent_v2'\n"
        "        else:\n"
        + nested_legacy
    )
    text = text[:start] + semantic_block + text[end:]

    CORE.write_text(text, encoding='utf-8')
    print('[ok] semantic agent v2 installed as primary core brain')


def patch_fastpath() -> None:
    text = FAST.read_text(encoding='utf-8')
    if FAST_MARKER in text:
        print('[skip] semantic-agent timeouts already active')
        return

    # Semantic planning adds one small inference before tool execution. Research can
    # also crawl public sources. Keep it in the background worker, but give normal
    # interactive turns enough time instead of incorrectly suggesting "missão longa".
    old = "_TIMEOUTS = {\n    'fast': 15,\n    'normal': 45,\n    'hard': 120,\n    'mission': 300,\n    'cron': 120,\n}\n"
    new = "_TIMEOUTS = {\n    'fast': 30,\n    'normal': 90,\n    'hard': 180,\n    'mission': 300,\n    'cron': 120,\n}\n" + FAST_MARKER + "\n"
    if old not in text:
        # Some local installs may already have adjusted values. In that case only
        # stamp the marker; never downgrade/overwrite a larger operator SLA.
        if '_TIMEOUTS = {' not in text:
            raise RuntimeError('fastpath timeout map not found')
        marker_pos = text.index('_TIMEOUTS = {')
        close = text.index('}\n', marker_pos) + 2
        current_block = text[marker_pos:close]
        current_block = current_block.replace("'fast': 15", "'fast': 30")
        current_block = current_block.replace("'normal': 45", "'normal': 90")
        current_block = current_block.replace("'hard': 120", "'hard': 180")
        text = text[:marker_pos] + current_block + FAST_MARKER + '\n' + text[close:]
    else:
        text = text.replace(old, new, 1)

    # Keep per-chat context available to every core invocation.
    env_anchor = "    env['HERMES_TRACE_ID'] = trace\n"
    if "env['HERMES_CHAT_KEY'] = key" not in text and "env['HERMES_CHAT_KEY'] = key or 'default'" not in text:
        if env_anchor not in text:
            raise RuntimeError('fastpath env anchor not found')
        text = text.replace(env_anchor, env_anchor + "    env['HERMES_CHAT_KEY'] = key or 'default'\n", 1)

    FAST.write_text(text, encoding='utf-8')
    print('[ok] fastpath SLA/context updated for semantic agent')


def main() -> int:
    for path in (CORE, FAST, ROOT / 'semantic_agent.py'):
        if not path.exists():
            raise SystemExit(f'missing runtime file: {path}')
    patch_core()
    patch_fastpath()
    print('OK: Semantic Agent V2 installed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
