"""PASS 4 beginner flows with local fakes only; no CLI account or socket bind."""
import email.message
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hub
from tests import test_hub as fixture


class BeginnerFlows(unittest.TestCase):
    # Borrow the isolated fixture without inheriting its unrelated test methods.
    setUp = fixture.HubCase.setUp
    request = fixture.HubCase.request
    login = fixture.HubCase.login
    api = fixture.HubCase.api
    send = fixture.HubCase.send
    done = fixture.HubCase.done
    calls = fixture.HubCase.calls
    responses = fixture.HubCase.responses

    def test_group_everyone_and_two_mentions_are_independent(self):
        other = self.h.create_agent({'name': 'Friend', 'role': 'Give an independent answer.'})['agent']['id']
        cid = self.h.group({'name': 'Pair', 'agents': [self.aid, other]})['chat']['id']
        self.responses(self.aid, [{'result': '@friend try the same answer'}] * 2)
        self.responses(other, [{'result': '@assistant copy this'}] * 2)
        everyone = self.send(cid, '@all Each share one idea')
        self.assertEqual(len(everyone['job_ids']), 2)
        for jid in everyone['job_ids']: self.done(jid)
        explicit = self.send(cid, '@assistant @friend Each share another idea')
        self.assertEqual(len(explicit['job_ids']), 2)
        for jid in explicit['job_ids']: self.done(jid)
        with self.h.lock:
            messages = [dict(row) for row in self.h.db.execute('SELECT role,text FROM messages WHERE chat_id=?', (cid,))]
            jobs = [dict(row) for row in self.h.db.execute('SELECT agent_id,independent FROM jobs WHERE chat_id=?', (cid,))]
        self.assertEqual(sum(m['role'] == 'user' for m in messages), 2)
        self.assertEqual(sum(m['role'] == 'assistant' for m in messages), 4)
        self.assertEqual(len(jobs), 4)
        self.assertEqual({j['agent_id'] for j in jobs}, {self.aid, other})
        self.assertTrue(all(j['independent'] for j in jobs))
        self.assertFalse(any('Handoff requested' in m['text'] for m in messages))

    def test_quick_start_creates_one_group_and_sends_once(self):
        first = self.h.quick_start({'question': 'Each name one task for today'})
        self.assertTrue(first['created'])
        second = self.h.quick_start({'question': 'A different task'})
        self.assertEqual(second, {'chat_id': first['chat_id'], 'created': False})
        with self.h.lock:
            chat = self.h.chat(first['chat_id'])
            messages = [dict(row) for row in self.h.db.execute('SELECT role,text FROM messages WHERE chat_id=?', (first['chat_id'],))]
            jobs = [dict(row) for row in self.h.db.execute('SELECT agent_id FROM jobs WHERE chat_id=?', (first['chat_id'],))]
        self.assertEqual(len(chat['agents']), 2)
        self.assertEqual([m['text'] for m in messages if m['role'] == 'user'], ['@all Each name one task for today'])
        self.assertEqual(len(jobs), 2)
        self.assertTrue(self.h.product_state()['getting_started']['completed'])

    def test_scratch_team_needs_no_git_and_exposes_plain_answers(self):
        def answer(aid, chat, prompt, jid):
            number = aid.rsplit('-', 1)[-1]
            return f'Answer: Octopus fact {number}.\nStatus: PASS\nEvidence: Local fake reply.'
        with mock.patch.object(self.h, '_git', side_effect=AssertionError('Git must not run for scratch teams')):
            with mock.patch.object(self.h, 'run_engine', side_effect=answer):
                created = self.h.create_swarm({'goal': 'Each give one octopus fact', 'shape': 'partition',
                    'working_dir': '', 'worktrees': False, 'workers': [{}, {}]})
                sid = created['id']
                result = fixture.poll(lambda: self.h.swarm(sid) if all(w['terminal'] for w in self.h.swarm(sid)['workers']) else None)
        self.assertEqual(len(result['workers']), 2)
        self.assertTrue(Path(result['working_dir']).is_dir())
        self.assertTrue(all(w['worktree'] is None for w in result['workers']))
        self.assertEqual([w['answer'] for w in result['workers']], ['Octopus fact 1.', 'Octopus fact 2.'])
        self.assertTrue(all(w['terminal'] for w in result['workers']))

    def test_merge_and_discard_reject_unfinished_worker(self):
        # Simulate an existing owned worktree in the database; validation must stop
        # before any Git command or filesystem mutation.
        release = threading.Event()
        def wait_for_review(*args):
            release.wait(2)
            return 'Answer: Done'
        with mock.patch.object(self.h, 'run_engine', side_effect=wait_for_review):
            created = self.h.create_swarm({'goal': 'Work', 'shape': 'partition', 'working_dir': '', 'workers': [{}]})
            sid = created['id']
            worker = self.h.swarm(sid)['workers'][0]
            try:
                with self.h.lock:
                    self.h.db.execute('UPDATE swarm_workers SET worktree=? WHERE agent_id=?', (str(self.root / 'fake-tree'), worker['agent_id']))
                    self.h.db.commit()
                with mock.patch.object(self.h, '_git', side_effect=AssertionError('Pending actions must not call Git')):
                    for action in ('merge', 'discard'):
                        with self.subTest(action=action), self.assertRaises(hub.HubError) as raised:
                            self.h.swarm_action({'id': sid, 'worker': worker['agent_id'], 'action': action})
                        self.assertEqual(raised.exception.status, 409)
            finally:
                release.set()
            self.done(worker['job_id'])

    def test_phone_check_requires_exact_configured_host_and_origin(self):
        configured = 'https://hub.example.ts.net'
        self.h.config['allowed_origins'] = [configured]
        local_status, local_heads, local_body = self.request('/api/phone-check')  # public local health
        self.assertEqual(local_status, 200)
        self.assertFalse(json.loads(local_body)['ok'])
        self.assertNotIn('Access-Control-Allow-Origin:', local_heads)
        status, heads, body = self.request('/api/phone-check', headers={
            'Host': 'hub.example.ts.net', 'Origin': 'http://127.0.0.1:4700'})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'ok': True, 'service': 'agent-hub', 'origin': configured})
        self.assertIn('Access-Control-Allow-Origin: http://127.0.0.1:4700', heads)
        self.assertEqual(self.request('/api/phone-check', headers={'Host': 'evil.example.ts.net'})[0], 403)
        self.assertEqual(self.request('/api/phone-check', headers={
            'Host': 'hub.example.ts.net', 'Origin': 'https://evil.example.ts.net'})[0], 403)

    def test_phone_setup_lists_linux_tailscale_download_for_hub_host(self):
        source = (hub.ROOT / 'static' / 'phone.js').read_text()
        self.assertIn("['Linux (Hub host)','https://tailscale.com/download/linux']", source)
        self.assertIn("['Mac (Hub host)','https://tailscale.com/download/mac']", source)

    def test_project_picker_route_reports_worktree_availability(self):
        self.cookie = self.login()
        expected = {'exists': True, 'is_git': True, 'git_root': str(self.root), 'worktrees_available': True}
        with mock.patch.object(self.h, 'project_info', return_value=expected) as checked:
            status, _, body = self.api('/api/project?path=' + str(self.root))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), expected)
        checked.assert_called_once_with(str(self.root))

    def test_stream_delta_reaches_sse_before_final_message(self):
        self.cookie = self.login()
        self.responses(self.aid, [{'stream': ['First ', 'answer'], 'stream_delay': .2, 'result': 'First answer'}])
        handler = hub.Handler.__new__(hub.Handler)
        handler.server = type('Server', (), {'hub': self.h, 'server_address': ('127.0.0.1', 4700)})()
        handler.connection = fixture.DummyConnection()
        handler.client_address = ('127.0.0.1', 12345)
        handler.path = '/api/events'
        handler.requestline = 'GET /api/events HTTP/1.1'
        handler.command = 'GET'
        handler.request_version = 'HTTP/1.1'
        handler.close_connection = False
        handler.rfile = io.BytesIO()
        handler.wfile = io.BytesIO()
        headers = email.message.Message()
        headers['Host'] = '127.0.0.1:4700'
        headers['Cookie'] = 'hub_session=' + self.cookie
        handler.headers = headers
        thread = threading.Thread(target=handler.dispatch, args=(False,), daemon=True)
        thread.start()
        try:
            fixture.poll(lambda: b'event: ready' in handler.wfile.getvalue())
            sent = self.send(text='Please answer')
            fixture.poll(lambda: b'"kind": "delta"' in handler.wfile.getvalue())
            with self.h.lock:
                self.assertFalse(self.h.db.execute("SELECT 1 FROM messages WHERE chat_id=? AND role='assistant'", (self.cid,)).fetchone())
            self.done(sent['job_id'])
            wire = handler.wfile.getvalue()
            self.assertIn(b'"text": "First "', wire)
            self.assertIn(b'"text": "First answer"', wire)
            self.assertLess(wire.index(b'"kind": "delta"'), wire.rindex(b'"kind": "message"'))
            self.assertIn(('"job_id": %d' % sent['job_id']).encode(), wire)
        finally:
            self.h.stop.set()
            self.h.emit('shutdown')
            thread.join(2)
        self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main()
