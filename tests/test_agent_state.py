from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core_v2'))

import agent_state


class AgentStateTests(unittest.TestCase):
    def test_refresh_builds_operational_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            state_file = state_dir / 'agent_state.json'
            tasks = [
                {'id': 't1', 'title': 'Entregar proposta', 'status': 'todo', 'priority': 'high', 'due': None, 'created_at': 1},
            ]
            goals = [
                {'id': 'g1', 'title': 'Fechar novo cliente', 'category': 'money', 'progress': 30},
            ]
            schedules = [
                {'id': 's1', 'kind': 'routine', 'message': 'Tomar água', 'next_at': 123, 'timezone': 'America/Sao_Paulo'},
            ]
            with patch.object(agent_state, 'STATE_DIR', state_dir), \
                 patch.object(agent_state, 'STATE_FILE', state_file), \
                 patch.object(agent_state, 'list_tasks', return_value=tasks), \
                 patch.object(agent_state, 'list_goals', return_value=goals), \
                 patch.object(agent_state, 'list_schedules', return_value=schedules), \
                 patch.object(agent_state, 'recent_decisions', return_value=[]):
                state = agent_state.refresh(current_context='falando da proposta')
                self.assertEqual(state['primary_goal']['id'], 'g1')
                self.assertEqual(state['today']['tasks_open'], 1)
                self.assertEqual(state['today']['active_schedules'], 1)
                self.assertEqual(state['next_actions'][0]['id'], 't1')
                self.assertIn('proposta', state['current_context'])
                self.assertTrue(state_file.exists())

    def test_note_turn_keeps_recent_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            state_file = state_dir / 'agent_state.json'
            with patch.object(agent_state, 'STATE_DIR', state_dir), \
                 patch.object(agent_state, 'STATE_FILE', state_file), \
                 patch.object(agent_state, 'list_tasks', return_value=[]), \
                 patch.object(agent_state, 'list_goals', return_value=[]), \
                 patch.object(agent_state, 'list_schedules', return_value=[]), \
                 patch.object(agent_state, 'recent_decisions', return_value=[]):
                state = agent_state.note_turn('terminei isso', 'Marquei como concluído')
                self.assertIn('terminei isso', state['current_context'])
                self.assertEqual(state['recent_results'][-1]['text'], 'Marquei como concluído')


if __name__ == '__main__':
    unittest.main()
