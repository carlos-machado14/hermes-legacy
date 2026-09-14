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

    anchor = "    direct_literal = _deterministic_reply(text)\n    if direct_literal is not None:\n        reply = direct_literal\n        route_name = 'deterministic_literal'\n    else:\n        followup_reply = _brief_followup_reply(text)\n"
    replacement = "    direct_literal = _deterministic_reply(text)\n    if direct_literal is not None:\n        reply = direct_literal\n        route_name = 'deterministic_literal'\n    else:\n        # Semantic Agent V2 is the primary brain. It understands the whole request,\n        # current conversation and available capabilities before choosing a tool.\n        # Legacy routers remain only as compatibility fallbacks.\n        semantic_agent_reply = handle_semantic_agent(text, _original_llm)\n        if semantic_agent_reply is not None:\n            reply = semantic_agent_reply\n            route_name = 'semantic_agent_v2'\n        else:\n            followup_reply = _brief_followup_reply(text)\n"
    if anchor not in text:
        raise RuntimeError('core_entry ask anchor not found')
    text = text.replace(anchor, replacement, 1)

    # The insertion adds one nesting level to the legacy fallback chain. Indent the
    # block from `if followup_reply` through the final fallback by four spaces.
    start = text.index("            followup_reply = _brief_followup_reply(text)\n") + len("            followup_reply = _brief_followup_reply(text)\n")
    end_marker = "\n    _persist_turn(text, reply)\n"
    end = text.index(end_marker, start)
    block = text[start:end]
    # Only indent lines that belong to the old fallback branch.
    block = ''.join(('    ' + line if line.strip() else line) for line in block.splitlines(True))
    text = text[:start] + block + text[end:]

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
        raise RuntimeError('fastpath timeout map not found')
    text = text.replace(old, new, 1)

    # Keep per-chat context available to every core invocation.
    env_anchor = "    env['HERMES_TRACE_ID'] = trace\n"
    if "env['HERMES_CHAT_KEY'] = key" not in text:
        if env_anchor not in text:
            raise RuntimeError('fastpath env anchor not found')
        text = text.replace(env_anchor, env_anchor + "    env['HERMES_CHAT_KEY'] = key\n", 1)

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
