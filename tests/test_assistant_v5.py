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
import time_service
import time_store
from complexity_router import classify
from temporal_parser import humanize, parse
from time_router import _message
from time_store import compute_next
from web_research import _company_queries, _looks_generic


class ComplexityV6Tests(unittest.TestCase):
    def test_complexity_is_language_agnostic(self):
        self.assertEqual(classify('curto').tier, 'fast')
        self.assertEqual(classify('x ' * 80).tier, 'normal')
        self.assertEqual(classify('x ' * 300).tier, 'hard')

    def test_same_size_has_same_tier_regardless_of_wording(self):
        first = 'alpha ' * 40
        second = 'beta ' * 40
        self.assertEqual(classify(first).tier, classify(second).tier)


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
        self.assertEqual(
            _message('Me lembre todo dia 28 do nosso aniversário de namoro'),
            'do nosso aniversário de namoro',
        )


class TimeStoreIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = time_store.DB_PATH
        time_store.DB_PATH = Path(self.tmp.name) / 'assistant.sqlite3'

    def tearDown(self):
        time_store.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_once_with_microseconds_finishes_after_first_occurrence(self):
        zone = ZoneInfo('America/Sao_Paulo')
        recurrence = {'freq': 'once', 'at': '2026-09-15T13:48:43.637622-03:00'}
        before = int(datetime(2026, 9, 15, 13, 46, 43, tzinfo=zone).timestamp())
        due = time_store.compute_next(recurrence, before, 'America/Sao_Paulo')
        self.assertIsNotNone(due)
        self.assertIsNone(time_store.compute_next(recurrence, due, 'America/Sao_Paulo'))

    def test_claim_due_never_returns_same_occurrence_twice(self):
        zone = ZoneInfo('America/Sao_Paulo')
        recurrence = {'freq': 'once', 'at': '2026-09-15T13:48:43.637622-03:00'}
        before = int(datetime(2026, 9, 15, 13, 46, 43, tzinfo=zone).timestamp())
        due = time_store.compute_next(recurrence, before, 'America/Sao_Paulo')
        self.assertIsNotNone(due)

        with time_store._conn() as conn:
            conn.execute(
                '''INSERT INTO schedules(
                    id,title,kind,message,timezone,recurrence_json,status,next_run_at,
                    snoozed_until,source,parent_id,metadata_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?, 'active', ?,NULL,?,NULL,'{}',?,?)''',
                (
                    'once-test', 'Lembrete - teste', 'reminder', 'teste',
                    'America/Sao_Paulo',
                    '{"freq":"once","at":"2026-09-15T13:48:43.637622-03:00"}',
                    due, 'test', before, before,
                ),
            )

        first = time_store.claim_due(now=due)
        self.assertEqual(len(first), 1)
        occurrence_id = first[0]['id']
        time_store.mark_delivery(occurrence_id, ok=True)

        second = time_store.claim_due(now=due + 20)
        third = time_store.claim_due(now=due + 60)
        self.assertEqual(second, [])
        self.assertEqual(third, [])

        schedule = time_store.get_schedule('once-test')
        self.assertEqual(schedule['status'], 'completed')
        self.assertIsNone(schedule['next_run_at'])
        with sqlite3.connect(time_store.DB_PATH) as conn:
            rows = conn.execute('SELECT status,attempts FROM schedule_occurrences WHERE schedule_id=?', ('once-test',)).fetchall()
        self.assertEqual(rows, [('delivered', 1)])


class LegacyReminderDedupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_store_db = time_store.DB_PATH
        self.old_service_db = time_service.DB_PATH
        db = Path(self.tmp.name) / 'assistant.sqlite3'
        time_store.DB_PATH = db
        time_service.DB_PATH = db
        with time_store._conn():
            pass

    def tearDown(self):
        time_store.DB_PATH = self.old_store_db
        time_service.DB_PATH = self.old_service_db
        self.tmp.cleanup()

    def test_duplicate_legacy_schedules_are_cancelled_but_natural_schedule_is_preserved(self):
        recurrence = '{"freq":"daily","time":"08:00"}'
        with sqlite3.connect(time_store.DB_PATH) as conn:
            for index in range(3):
                conn.execute(
                    '''INSERT INTO schedules(
                        id,title,kind,message,timezone,recurrence_json,status,next_run_at,
                        snoozed_until,source,parent_id,metadata_json,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?, 'active', ?,NULL,?,NULL,'{}',?,?)''',
                    (
                        f'legacy-{index}', 'Água', 'reminder', 'Beber água',
                        'America/Sao_Paulo', recurrence, 1000 + index,
                        'legacy-cron-migration', 100 + index, 100 + index,
                    ),
                )
            conn.execute(
                '''INSERT INTO schedules(
                    id,title,kind,message,timezone,recurrence_json,status,next_run_at,
                    snoozed_until,source,parent_id,metadata_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?, 'active', ?,NULL,?,NULL,'{}',?,?)''',
                (
                    'natural-1', 'Água manual', 'reminder', 'Beber água',
                    'America/Sao_Paulo', recurrence, 1000,
                    'natural-language', 200, 200,
                ),
            )
            conn.commit()

        cancelled = time_service._dedupe_legacy_schedules()
        self.assertEqual(cancelled, 2)

        with sqlite3.connect(time_store.DB_PATH) as conn:
            legacy = conn.execute(
                "SELECT status,COUNT(*) FROM schedules WHERE source='legacy-cron-migration' GROUP BY status"
            ).fetchall()
            natural = conn.execute("SELECT status FROM schedules WHERE id='natural-1'").fetchone()[0]
        self.assertIn(('active', 1), legacy)
        self.assertIn(('cancelled', 2), legacy)
        self.assertEqual(natural, 'active')


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
