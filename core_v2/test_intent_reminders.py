from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from goal_execution_engine import classify_task
from temporal_parser import parse
from time_router import _creation_intent, _query_intent, _message


class HermesIntentReminderTests(unittest.TestCase):
    def test_question_about_existing_alert_is_not_creation(self) -> None:
        text = 'Dúvida estamos com 2 alertas para hoje às 8:30?'
        self.assertTrue(_query_intent(text))
        self.assertFalse(_creation_intent(text))

    def test_direct_reminder_is_creation(self) -> None:
        text = 'Me avisa amanhã às 8:30 que preciso enviar as atualizações para o André'
        self.assertFalse(_query_intent(text))
        self.assertTrue(_creation_intent(text))

    def test_interval_with_between_window(self) -> None:
        now = datetime(2026, 9, 16, 6, 45, tzinfo=ZoneInfo('America/Sao_Paulo'))
        parsed = parse(
            'Quero que vc me avise todos os dias da semana entre as 8 e as 17h para lembrar de tomar água a cada 15 min',
            now=now,
        )
        self.assertIsNotNone(parsed)
        recurrence = parsed['recurrence']
        self.assertEqual(recurrence['freq'], 'interval')
        self.assertEqual(recurrence['minutes'], 15)
        self.assertEqual(recurrence['window_start'], '08:00')
        self.assertEqual(recurrence['window_end'], '17:00')
        next_run = datetime.fromtimestamp(parsed['next_run_at'], ZoneInfo('America/Sao_Paulo'))
        self.assertEqual((next_run.hour, next_run.minute), (8, 0))

    def test_reminder_message_is_cleaned(self) -> None:
        text = 'Me avisa amanhã às 8:30 que preciso enviar as atualizações para o André'
        self.assertEqual(_message(text), 'preciso enviar as atualizações para o André')

    def test_schedule_backed_commitment_does_not_require_external_approval(self) -> None:
        task = {
            'title': 'preciso enviar as atualizações para o André',
            'kind': 'commitment',
            'metadata': {'source': 'natural-language', 'schedule_id': 'abc123'},
        }
        classified = classify_task(task)
        self.assertEqual(classified['kind'], 'scheduled_reminder')
        self.assertEqual(classified['risk'], 'low')
        self.assertFalse(classified['requires_approval'])


if __name__ == '__main__':
    unittest.main()
