from __future__ import annotations

import inspect

import core_v2.core_entry as core_entry


def test_core_routes_through_semantic_brain():
    source = inspect.getsource(core_entry)
    assert 'brain_decide' in source
    assert 'execute_intent' in source
    assert 'local_fastpath' not in source
    assert 'conversation_action_router' not in source
    assert 'handle_task_command' not in source
    assert 'handle_time_command' not in source


def test_removed_phrase_router_modules_are_not_imported():
    source = inspect.getsource(core_entry)
    assert 'local_action_intent' not in source
    assert '_PERSONAL_HINTS' not in source
    assert '_EXACT_REPLY_RE' not in source
