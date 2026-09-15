from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'core_v2'
sys.path.insert(0, str(CORE))

from complexity_router import classify
from temporal_parser import humanize, parse
from time_store import compute_next


class ComplexityV5Tests(unittest.TestCase):
    def test_natural_complex_work_becomes_mission(self):
        cases = [
            'Quero encontrar um possível cliente em Colombo PR que esteja perdendo oportunidade por não ter uma boa presença digital. Analise e me traga o melhor.',
            'Voce precisa me trazer os dados de 1 empresa que precisa de um site com todos os dados, links e imagens.',
            'Implemente tudo no projeto e valide os testes.',
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(classify(text).tier, 'mission')

    def test_simple_question_stays_normal(self):
        self.assertEqual(classify('Qual a capital da Itália?').tier, 'normal')


class TimeEngineParsingTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 15, 10, 0, tzinfo=ZoneInfo('America/Sao_Paulo'))

    def test_water_window(self):
        result = parse('me lembre de beber água a cada 15 minutos das 8h até 17h de segunda a sexta', now=self.now)
        self.assertIsNotNone(result)
        rec = result['recurrence']
        self.assertEqual(rec['freq'], 'interval')
        self.assertEqual(rec['minutes'], 15)
        self.assertEqual(rec['window_start'], '08:00')
        self.assertEqual(rec['window_end'], '17:00')
        self.assertEqual(rec['weekdays'], [0,1,2,3,4])

    def test_monthly_day_28(self):
        result = parse('me lembre todo dia 28 do nosso aniversário de namoro', now=self.now)
        self.assertEqual(result['recurrence']['freq'], 'monthly')
        self.assertEqual(result['recurrence']['day'], 28)
        self.assertIn('todo dia 28', humanize(result['recurrence']))

    def test_yearly_requires_month_when_missing(self):
        result = parse('todo ano dia 28 me lembre do aniversário', now=self.now)
        self.assertIn('needs_clarification', result)

    def test_yearly_with_month(self):
        result = parse('todo ano dia 12 de junho me lembre do aniversário', now=self.now)
        self.assertEqual(result['recurrence']['freq'], 'yearly')
        self.assertEqual(result['recurrence']['month'], 6)
        self.assertEqual(result['recurrence']['day'], 12)

    def test_interval_stays_inside_window(self):
        rec = {'freq':'interval','minutes':15,'window_start':'08:00','window_end':'17:00','weekdays':[0,1,2,3,4]}
        after = int(datetime(2026,9,15,16,52,tzinfo=ZoneInfo('America/Sao_Paulo')).timestamp())
        nxt = datetime.fromtimestamp(compute_next(rec, after, 'America/Sao_Paulo'), ZoneInfo('America/Sao_Paulo'))
        self.assertEqual((nxt.hour,nxt.minute),(17,0))


if __name__ == '__main__':
    unittest.main()
