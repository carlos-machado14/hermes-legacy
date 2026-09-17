#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'core_v2'
PLUGIN = ROOT / 'plugins' / 'hermes-core-fastpath' / '__init__.py'
sys.path.insert(0, str(CORE))

from complexity_router import classify  # noqa: E402


def load_gateway():
    spec = importlib.util.spec_from_file_location('hermes_semantic_gateway_test', PLUGIN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gateway = load_gateway()


class ComplexityRouterTests(unittest.TestCase):
    def setUp(self):
        self.old = os.environ.pop('HERMES_COMPLEXITY', None)

    def tearDown(self):
        if self.old is not None:
            os.environ['HERMES_COMPLEXITY'] = self.old
        else:
            os.environ.pop('HERMES_COMPLEXITY', None)

    def test_language_agnostic_size_profiles(self):
        self.assertEqual(classify('curto').tier, 'fast')
        self.assertEqual(classify('x ' * 80).tier, 'normal')
        self.assertEqual(classify('x ' * 300).tier, 'hard')

    def test_forced_tier(self):
        for tier in ('fast', 'normal', 'hard', 'mission'):
            with self.subTest(tier=tier):
                os.environ['HERMES_COMPLEXITY'] = tier
                self.assertEqual(classify('qualquer texto').tier, tier)


class SemanticGatewayContractTests(unittest.TestCase):
    def test_phrase_routers_were_removed(self):
        for name in (
            'TIME_RE', 'CRON_RE', 'CONTINUE_RE', 'CANCEL_RE', 'REPLACE_RE',
            '_HARD_HINTS', '_RESEARCH_HINTS', '_MULTI_HINTS', '_IMPLEMENT_HINTS', '_MISSION_HINTS',
        ):
            self.assertFalse(hasattr(gateway, name), name)

    def test_gateway_always_delegates_text_to_core(self):
        self.assertTrue(callable(gateway._run_core))
        self.assertFalse(hasattr(gateway, '_run_time'))
        self.assertFalse(hasattr(gateway, '_classify_complexity'))

    def test_message_split(self):
        self.assertEqual(gateway._split_message('abc'), ['abc'])
        long_text = ('linha de teste ' * 500).strip()
        chunks = gateway._split_message(long_text, limit=500)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 530 for chunk in chunks))


if __name__ == '__main__':
    unittest.main()
