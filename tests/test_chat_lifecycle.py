"""Regressions for Guide Undo, team cards, and routine run dates."""
import json
import unittest
from unittest import mock

import hub
import test_hub


class Lifecycle(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    responses = test_hub.HubCase.responses
    def guide_card(self, mid):
        return next(m for m in self.h.history(self.h.guide_chat())['messages'] if m['id'] == mid)['cards'][0]

    def test_guide_undo_restores_durable_actionable_agent_card(self):
        spec = {'action': 'create_agent', 'name': 'Writer', 'instructions': 'Write clearly.'}
        mid = self.h.add_message(self.h.guide_chat(), self.h.guide_id(), 'assistant',
                                 '```agent-hub\n' + json.dumps(spec) + '\n```')
        self.h.db.commit()
        created = self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'create'})
        self.assertEqual(self.guide_card(mid)['status'], 'created')
        with mock.patch.object(self.h, 'emit', wraps=self.h.emit) as emitted:
            self.h.archive({'kind': 'agent', 'id': created['result']['agent']['id']})
        self.assertIn(mock.call('message', self.h.guide_chat()), emitted.call_args_list)
        self.assertEqual(self.guide_card(mid)['status'], 'pending')
        self.assertNotIn('result', self.guide_card(mid))
        self.h.close()
        self.h = hub.Hub(self.root, dict(self.h.config), defer_token=True)
        self.assertEqual(self.guide_card(mid)['status'], 'pending')
        recreated = self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'create'})
        self.assertFalse(recreated.get('duplicate'))
        self.assertEqual(recreated['result']['agent']['id'], 'writer')
        self.assertEqual(self.guide_card(mid)['status'], 'created')

    def test_guide_undo_restores_group_card(self):
        spec = {'action': 'create_group', 'name': 'Reviewers', 'agents': ['Assistant', 'Guide']}
        mid = self.h.add_message(self.h.guide_chat(), self.h.guide_id(), 'assistant',
                                 '```agent-hub\n' + json.dumps(spec) + '\n```')
        self.h.db.commit()
        made = self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'create'})
        self.h.archive({'kind': 'group', 'id': made['result']['chat']['id']})
        self.assertEqual(self.guide_card(mid)['status'], 'pending')
        self.assertNotIn('result', self.guide_card(mid))

    def test_team_card_attaches_to_active_history_once(self):
        source = self.h.group({'name': 'Project', 'agents': ['assistant', 'guide']})['chat']['id']
        active = self.h.history(source)['active_version']
        self.assertIsNotNone(active)
        with mock.patch.object(self.h, 'send', return_value={'job_id': 999}):
            made = self.h.create_swarm({'goal': 'Compare options', 'shape': 'partition',
                                        'source_chat_id': source, 'workers': [{'source_agent_id': 'assistant'}]})
        cards = [c for m in self.h.history(source)['messages'] for c in m['cards'] if c['kind'] == 'team_task']
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['swarm_id'], made['id'])
        self.h._update_result_card(made['id'])
        ids = [m['id'] for m in self.h.history(source)['messages'] if any(c['kind'] == 'team_task' for c in m['cards'])]
        self.assertEqual(ids, [made['result_message_id']])
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM version_messages WHERE version_id=? AND message_id=?',
                           (active, ids[0])).fetchone()[0], 1)

    def test_group_recreate_reuses_live_children_or_recreates_undo_archived_children(self):
        for archive_children in (False, True):
            with self.subTest(archive_children=archive_children):
                name = 'Undo Child' if archive_children else 'Live Child'
                spec = {'action': 'create_group', 'name': name + ' Group', 'agents': [
                    {'action': 'create_agent', 'name': name, 'instructions': 'Write clearly.'}, 'Assistant']}
                mid = self.h.add_message(self.h.guide_chat(), self.h.guide_id(), 'assistant',
                                         '```agent-hub\n' + json.dumps(spec) + '\n```')
                self.h.db.commit()
                made = self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'create'})
                child = made['result']['chat']['agents'][0]
                self.h.archive({'kind': 'group', 'id': made['result']['chat']['id']})
                if archive_children:
                    self.h.archive({'kind': 'agent', 'id': child})
                recreated = self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'create'})
                self.assertFalse(recreated.get('duplicate'))
                self.assertEqual(recreated['result']['chat']['agents'], [child, 'assistant'])
                self.assertEqual(self.guide_card(mid)['status'], 'created')

    def test_last_run_only_when_work_was_queued(self):
        clock = [1800000000]
        self.h.clock = lambda: clock[0]
        routine = self.h.create_routine({'agent_id': 'assistant', 'name': 'Briefing', 'prompt': 'Brief me',
                                         'trigger': 'interval', 'minutes': 5})['routine']
        self.h.tick_routines(routine['next_run'] + 3600)
        self.assertIsNone(self.h.routines()['routines'][0]['last_run'])
        clock[0] = routine['next_run'] + 3601
        self.h.toggle_routine({'id': routine['id'], 'enabled': False})
        self.h.toggle_routine({'id': routine['id'], 'enabled': True})
        due = self.h.routines()['routines'][0]['next_run']
        with mock.patch.object(self.h, 'enqueue', side_effect=RuntimeError('worker unavailable')):
            self.h.tick_routines(due)
        self.assertIsNone(self.h.routines()['routines'][0]['last_run'])

        self.h.db.execute("UPDATE jobs SET status='error' WHERE status='queued'")
        self.h.db.commit()
        clock[0] = due + 1
        self.h.toggle_routine({'id': routine['id'], 'enabled': False})
        self.h.toggle_routine({'id': routine['id'], 'enabled': True})
        due = self.h.routines()['routines'][0]['next_run']
        with mock.patch.object(self.h, 'enqueue'):
            self.h.tick_routines(due)
        self.assertIsNone(self.h.routines()['routines'][0]['last_run'])
        job_id = self.h.db.execute('SELECT job_id FROM routine_runs WHERE routine_id=? AND due=?',
                                   (routine['id'], due)).fetchone()[0]
        self.responses('assistant', [{'result': 'Briefing complete.'}])
        self.h.enqueue('assistant', job_id)
        test_hub.HubCase.done(self, job_id)
        started = self.h.db.execute('SELECT started FROM jobs WHERE id=?', (job_id,)).fetchone()[0]
        self.assertIsNotNone(started)
        self.assertEqual(self.h.routines()['routines'][0]['last_run'], started)
        clock[0] = due + 1
        self.h.toggle_routine({'id': routine['id'], 'enabled': False})
        self.h.toggle_routine({'id': routine['id'], 'enabled': True})
        skipped = self.h.routines()['routines'][0]['next_run']
        self.h.tick_routines(skipped)
        self.assertEqual(self.h.routines()['routines'][0]['last_run'], started)


if __name__ == '__main__':
    unittest.main()
