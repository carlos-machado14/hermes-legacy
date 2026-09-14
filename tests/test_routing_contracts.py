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


def load_fastpath():
    spec = importlib.util.spec_from_file_location('hermes_core_fastpath_test', PLUGIN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fastpath = load_fastpath()


class ComplexityRouterTests(unittest.TestCase):
    def setUp(self):
        self.old = os.environ.pop('HERMES_COMPLEXITY', None)

    def tearDown(self):
        if self.old is not None:
            os.environ['HERMES_COMPLEXITY'] = self.old
        else:
            os.environ.pop('HERMES_COMPLEXITY', None)

    def test_contract_cases(self):
        cases = [
            ('Responda apenas: OK', 'fast'),
            ('Responde somente: PONG', 'fast'),
            ('Qual a capital da Itália?', 'normal'),
            ('Explique o que é Redis.', 'normal'),
            ('Meus projetos estão saudáveis?', 'normal'),
            ('Lembra do meu projeto de viagem?', 'normal'),
            ('Isso faz sentido?', 'normal'),
            ('Continue', 'normal'),
            ('Analise profundamente esta arquitetura e diagnostique gargalos.', 'hard'),
            ('Faça uma análise profunda e passo a passo do sistema.', 'hard'),
            ('Investigue a causa raiz deste erro e compare opções de correção.', 'hard'),
            ('Refatore detalhadamente toda esta arquitetura e explique os trade-offs.', 'hard'),
            ('missão: revise o projeto inteiro e entregue a correção', 'mission'),
            ('execute até finalizar a análise do projeto', 'mission'),
            ('trabalhe até concluir o diagnóstico', 'mission'),
            ('faça até finalizar a implementação', 'mission'),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(classify(text).tier, expected)

    def test_forced_tier(self):
        for tier in ('fast', 'normal', 'hard', 'mission'):
            with self.subTest(tier=tier):
                os.environ['HERMES_COMPLEXITY'] = tier
                self.assertEqual(classify('qualquer texto').tier, tier)


class FastPathContractTests(unittest.TestCase):
    def test_cron_detection(self):
        positives = [
            'quais rotinas eu tenho?',
            'minhas rotinas',
            'listar crons',
            'crie uma rotina todo dia às 8h',
            'me lembre amanhã',
            'todo dia me mande notícias',
            'pause a rotina notícias',
            'rode a rotina agora',
            'melhore o briefing das rotinas',
        ]
        negatives = [
            'qual a capital da Itália?',
            'me diga suas três principais funções',
            'responda apenas: OK',
            'como funciona redis?',
            'analise meu código Flutter',
            'quero conversar sobre arquitetura',
        ]
        for text in positives:
            with self.subTest(text=text):
                self.assertIsNotNone(fastpath.CRON_RE.search(text))
        for text in negatives:
            with self.subTest(text=text):
                self.assertIsNone(fastpath.CRON_RE.search(text))

    def test_cancel_detection(self):
        positives = [
            'pare', 'para', 'cancele', 'cancela', 'cancelar', 'interrompa',
            'esquece isso', 'esqueça isso', 'deixa pra lá', 'deixe pra lá',
            'para isso', 'pare isso',
        ]
        negatives = [
            'pare a rotina notícias',
            'cancelar a rotina x',
            'como cancelar uma assinatura?',
            'não pare ainda',
        ]
        for text in positives:
            with self.subTest(text=text):
                self.assertIsNotNone(fastpath.CANCEL_RE.match(text))
        for text in negatives:
            with self.subTest(text=text):
                self.assertIsNone(fastpath.CANCEL_RE.match(text))

    def test_replace_detection(self):
        cases = [
            ('esquece isso e me fale sobre Roma', 'me fale sobre Roma'),
            ('cancela isso, agora veja o status da VPS', 'agora veja o status da VPS'),
            ('deixa isso e explique Redis', 'explique Redis'),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                match = fastpath.REPLACE_RE.match(text)
                self.assertIsNotNone(match)
                self.assertEqual(match.group(1).strip(), expected)

    def test_fastpath_complexity(self):
        cases = [
            ('Responda apenas: OK', False, 'fast'),
            ('Qual a capital da Itália?', False, 'normal'),
            ('Analise profundamente esta arquitetura e diagnostique a causa raiz.', False, 'hard'),
            ('missão: faça tudo e finalize', False, 'mission'),
            ('quais rotinas eu tenho?', True, 'cron'),
        ]
        for text, is_cron, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(fastpath._classify_complexity(text, is_cron), expected)

    def test_message_split(self):
        self.assertEqual(fastpath._split_message('abc'), ['abc'])
        long_text = ('linha de teste ' * 500).strip()
        chunks = fastpath._split_message(long_text, limit=500)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 520 for chunk in chunks))


if __name__ == '__main__':
    unittest.main()
