"""PASS 10: every skipped, failed, or uncertain schedule is visible once."""
import json
import unittest
from unittest import mock
import test_hub


class ScheduleNotices(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    done = test_hub.HubCase.done
    responses = test_hub.HubCase.responses

    def create(self):
        self.h.clock = lambda: 1800000000
        return self.h.create_routine({'agent_id':'assistant', 'name':'Morning briefing',
            'prompt':'Brief me', 'trigger':'interval', 'minutes':5})['routine']

    def notices(self):
        return [m['text'] for m in self.h.history('agent:assistant')['messages'] if "didn't run at" in m['text']]

    def test_missed_offline_run_skipped_once_and_next_scheduled(self):
        r = self.create()
        self.h.tick_routines(r['next_run'] + 3600)
        self.h.tick_routines(r['next_run'] + 3600)
        self.assertEqual(len(self.notices()), 1)
        self.assertIn('Hub was off', self.notices()[0])
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM jobs').fetchone()[0], 0)
        self.assertGreater(self.h.routines()['routines'][0]['next_run'], r['next_run'] + 3600)
        self.assertIn('Hub was off', self.h.routines()['routines'][0]['error'])

    def test_active_work_skip_visible(self):
        r = self.create()
        with mock.patch.object(self.h, 'enqueue'):
            self.h.send({'chat_id':'agent:assistant','text':'Working','request_id':'schedule-active'})
            self.h.tick_routines(r['next_run'])
        self.assertEqual(len(self.notices()), 1)
        self.assertIn('already has active work', self.notices()[0])

    def test_enqueue_failure_is_visible_and_not_replayed(self):
        r = self.create()
        with mock.patch.object(self.h, 'enqueue', side_effect=RuntimeError('worker unavailable')):
            self.h.tick_routines(r['next_run'])
        self.h.reconcile_routine_runs()
        self.assertEqual(len(self.notices()), 1)
        self.assertIn('failed: worker unavailable', self.notices()[0])

    def test_terminal_job_failure_and_restart_uncertainty_visible_once(self):
        for state in ('error', 'interrupted', 'uncertain'):
            r = self.create()
            with mock.patch.object(self.h, 'enqueue'):
                self.h.tick_routines(r['next_run'])
            job = self.h.db.execute('SELECT job_id FROM routine_runs WHERE routine_id=?', (r['id'],)).fetchone()[0]
            self.assertIsNotNone(job)
            self.h.status(job, state, 'provider stopped')
            self.h.reconcile_routine_runs()
            self.h.reconcile_routine_runs()
            row = self.h.db.execute('SELECT notice FROM routine_runs WHERE routine_id=?', (r['id'],)).fetchone()[0]
            self.assertIn('provider stopped', row)
            self.h.toggle_routine({'id':r['id'], 'enabled':False})
        self.assertEqual(len(self.notices()), 3)

    def test_usage_hold_is_pending_and_success_is_not_marked_failed(self):
        r = self.create()
        with mock.patch.object(self.h, 'enqueue'):
            self.h.tick_routines(r['next_run'])
        job = self.h.db.execute('SELECT job_id FROM routine_runs WHERE routine_id=?', (r['id'],)).fetchone()[0]
        self.h.status(job, 'held_limit', 'Quota reached')
        self.h.reconcile_routine_runs()
        self.assertEqual(self.notices(), [])
        self.h.status(job, 'done')
        self.h.reconcile_routine_runs()
        self.assertEqual(self.notices(), [])
        self.assertIsNone(self.h.routines()['routines'][0]['error'])

    def test_reserved_occurrence_without_job_is_uncertain(self):
        r = self.create()
        self.h.db.execute('INSERT INTO routine_runs(routine_id,due) VALUES(?,?)', (r['id'], r['next_run']))
        self.h.db.commit()
        self.h.reconcile_routine_runs()
        self.assertIn('uncertain:', self.notices()[0])
        self.h.tick_routines(r['next_run'])
        self.assertEqual(len(self.notices()), 1)
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM jobs').fetchone()[0], 0)

    def test_success_does_not_get_failure_notice(self):
        r = self.create()
        self.responses('assistant', [{'result':'SILENT'}])
        self.h.tick_routines(r['next_run'])
        self.done(self.h.db.execute('SELECT job_id FROM routine_runs WHERE routine_id=?', (r['id'],)).fetchone()[0])
        self.h.reconcile_routine_runs()
        self.assertEqual(self.notices(), [])
        self.assertIsNone(self.h.routines()['routines'][0]['error'])

if __name__ == '__main__': unittest.main()
