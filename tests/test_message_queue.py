"""Same-Pip queue regression without a real model or network."""
import threading
import unittest
from unittest import mock

import test_hub


class SamePipQueue(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    send = test_hub.HubCase.send
    done = test_hub.HubCase.done

    def test_second_message_is_saved_while_first_turn_runs_and_seen_when_it_starts(self):
        first_started = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()
        release_second = threading.Event()
        self.addCleanup(release_first.set)
        self.addCleanup(release_second.set)
        calls = []

        def blocked_model(aid, chat, prompt, jid, **kwargs):
            calls.append((aid, prompt, jid))
            self.h.status(jid, 'working')
            self.h.status(jid, 'typing')
            if len(calls) == 1:
                first_started.set()
                if not release_first.wait(5):
                    raise AssertionError('first turn was not released')
            else:
                second_started.set()
                if not release_second.wait(5):
                    raise AssertionError('second turn was not released')
            return 'Answer ' + str(len(calls))

        with mock.patch.object(self.h, 'run_engine', side_effect=blocked_model):
            first = self.send(text='first request')
            self.assertTrue(first_started.wait(3))
            second = self.send(text='second request')

            with self.h.lock:
                rows = [dict(r) for r in self.h.db.execute(
                    'SELECT id,text,created,seen_at FROM messages WHERE id IN (?,?) ORDER BY id',
                    (first['message_id'], second['message_id']))]
                jobs = [dict(r) for r in self.h.db.execute(
                    'SELECT id,status,started,finished FROM jobs WHERE id IN (?,?) ORDER BY id',
                    (first['job_id'], second['job_id']))]
            self.assertEqual([r['text'] for r in rows], ['first request', 'second request'])
            self.assertLess(rows[0]['id'], rows[1]['id'])
            self.assertLessEqual(rows[0]['created'], rows[1]['created'])
            self.assertIsNotNone(rows[0]['seen_at'])
            self.assertIsNone(rows[1]['seen_at'])
            self.assertIn(jobs[0]['status'], ('working', 'typing'))
            self.assertEqual(jobs[1]['status'], 'queued')
            self.assertIsNone(jobs[1]['started'])
            self.assertFalse(second_started.is_set())
            self.assertEqual([c[2] for c in calls], [first['job_id']])

            release_first.set()
            self.done(first['job_id'])
            self.assertTrue(second_started.wait(3))
            with self.h.lock:
                first_job = dict(self.h.db.execute('SELECT status,finished FROM jobs WHERE id=?',
                                                   (first['job_id'],)).fetchone())
                second_seen = self.h.db.execute('SELECT seen_at FROM messages WHERE id=?',
                                                (second['message_id'],)).fetchone()['seen_at']
            self.assertEqual(first_job['status'], 'done')
            self.assertIsNotNone(second_seen)
            self.assertGreaterEqual(second_seen, first_job['finished'])
            self.assertEqual([c[2] for c in calls], [first['job_id'], second['job_id']])

            release_second.set()
            self.done(second['job_id'])
            messages = self.h.history(self.cid)['messages']
            self.assertEqual([(m['role'], m['text']) for m in messages],
                             [('user', 'first request'), ('user', 'second request'),
                              ('assistant', 'Answer 1'), ('assistant', 'Answer 2')])
            self.assertEqual([m['id'] for m in messages], sorted(m['id'] for m in messages))
            self.assertEqual([m['created'] for m in messages], sorted(m['created'] for m in messages))
            self.assertEqual(self.h.db.execute("SELECT count(*) FROM jobs WHERE status='stopped'").fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
