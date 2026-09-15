from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'core_v2'
sys.path.insert(0, str(CORE))

import job_store
from complexity_router import classify
from temporal_parser import humanize, parse
from time_router import _message
from time_store import compute_next
from web_research import _company_queries, _looks_generic


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
        self.assertEqual(rec['weekdays'], [0, 1, 2, 3, 4])

    def test_monthly_day_28(self):
        result = parse('me lembre todo dia 28 do nosso aniversário de namoro', now=self.now)
        self.assertEqual(result['recurrence']['freq'], 'monthly')
        self.assertEqual(result['recurrence']['day'], 28)
        self.assertIn('todo dia 28', humanize(result['recurrence']))

    def test_daily_clock_without_h_suffix(self):
        result = parse('todo dia às 8 me lembre de revisar minhas prioridades', now=self.now)
        self.assertEqual(result['recurrence']['freq'], 'daily')
        self.assertEqual(result['recurrence']['time'], '08:00')

    def test_yearly_requires_month_when_missing(self):
        result = parse('todo ano dia 28 me lembre do aniversário', now=self.now)
        self.assertIn('needs_clarification', result)

    def test_yearly_with_month(self):
        result = parse('todo ano dia 12 de junho me lembre do aniversário', now=self.now)
        self.assertEqual(result['recurrence']['freq'], 'yearly')
        self.assertEqual(result['recurrence']['month'], 6)
        self.assertEqual(result['recurrence']['day'], 12)

    def test_interval_stays_inside_window(self):
        rec = {'freq': 'interval', 'minutes': 15, 'window_start': '08:00', 'window_end': '17:00', 'weekdays': [0, 1, 2, 3, 4]}
        after = int(datetime(2026, 9, 15, 16, 52, tzinfo=ZoneInfo('America/Sao_Paulo')).timestamp())
        nxt = datetime.fromtimestamp(compute_next(rec, after, 'America/Sao_Paulo'), ZoneInfo('America/Sao_Paulo'))
        self.assertEqual((nxt.hour, nxt.minute), (17, 0))

    def test_relative_time_removed_from_reminder_message(self):
        self.assertEqual(_message('Me lembre daqui a 2 minutos de testar o Hermes'), 'testar o Hermes')

    def test_monthly_time_removed_from_reminder_message(self):
        # The cadence is removed while the natural Portuguese preposition is kept.
        self.assertEqual(
            _message('Me lembre todo dia 28 do nosso aniversário de namoro'),
            'do nosso aniversário de namoro',
        )


class MultiFlowStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = job_store.DB_PATH
        job_store.DB_PATH = Path(self.tmp.name) / 'jobs.sqlite3'

    def tearDown(self):
        job_store.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_same_chat_can_have_multiple_independent_jobs(self):
        first = job_store.create_job('pesquise um cliente em Colombo PR', source_platform='telegram', source_chat_id='42')
        second = job_store.create_job('analise o repositório X', source_platform='telegram', source_chat_id='42')
        self.assertNotEqual(first['id'], second['id'])
        claimed = job_store.claim_jobs(2)
        self.assertEqual({row['id'] for row in claimed}, {first['id'], second['id']})
        self.assertTrue(all(row['status'] == 'claimed' for row in claimed))

    def test_legacy_jobs_database_is_migrated_before_notification_index(self):
        legacy = sqlite3.connect(job_store.DB_PATH)
        legacy.executescript(
            '''
            CREATE TABLE jobs (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              request TEXT NOT NULL,
              status TEXT NOT NULL,
              plan_json TEXT NOT NULL DEFAULT '[]',
              current_step INTEGER NOT NULL DEFAULT 0,
              result TEXT NOT NULL DEFAULT '',
              error TEXT NOT NULL DEFAULT '',
              attempts INTEGER NOT NULL DEFAULT 0,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );
            INSERT INTO jobs(id,title,request,status,created_at,updated_at)
            VALUES('legacyjob','Legacy','teste','running',1,1);
            '''
        )
        legacy.commit()
        legacy.close()

        recovered = job_store.recover_interrupted()
        self.assertEqual(recovered, 1)
        with sqlite3.connect(job_store.DB_PATH) as conn:
            cols = {row[1] for row in conn.execute('PRAGMA table_info(jobs)').fetchall()}
            indexes = {row[1] for row in conn.execute("PRAGMA index_list('jobs')").fetchall()}
            status = conn.execute("SELECT status FROM jobs WHERE id='legacyjob'").fetchone()[0]
        self.assertTrue({'source_platform', 'source_chat_id', 'source_user_id', 'notified_at'} <= cols)
        self.assertIn('idx_jobs_notify', indexes)
        self.assertEqual(status, 'queued')


class CompanyResearchFilteringTests(unittest.TestCase):
    def test_generic_articles_and_directories_are_not_business_candidates(self):
        generic = {
            'title': 'Como Encontrar Novos Clientes em 10 passos',
            'url': 'https://sebrae.com.br/artigo/clientes',
            'content': 'Guia completo para empresas.',
        }
        self.assertTrue(_looks_generic(generic))

    def test_local_prospect_request_becomes_entity_discovery_queries(self):
        queries = _company_queries(
            'Quero encontrar um possível cliente em Colombo PR que esteja perdendo oportunidade por não ter uma boa presença digital.'
        )
        self.assertGreaterEqual(len(queries), 4)
        self.assertTrue(all('Colombo PR' in query for query in queries))
        self.assertTrue(any('instagram telefone' in query for query in queries))


if __name__ == '__main__':
    unittest.main()
