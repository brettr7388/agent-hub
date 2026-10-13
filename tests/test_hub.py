"""Isolated Agent Hub integration checks; no network or real Claude invocation."""
import email.message
import io
import json
import os
from pathlib import Path
import http.client
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.parse import quote
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hub

FAKE = Path(__file__).with_name('fake_claude.py').resolve()


def poll(predicate, timeout=5):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        value = predicate()
        if value:
            return value
        time.sleep(.015)
    raise AssertionError('timed out waiting for hub state')


class DummyConnection:
    def settimeout(self, seconds):
        self.timeout = seconds


class HubCase(unittest.TestCase):
    def setUp(self):
        scratch = hub.ROOT / 'data' / 'test-runs'
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='hub-test-', dir=str(scratch))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        fake_account = self.root / 'fake-source-codex-home'
        fake_account.mkdir()
        (fake_account / 'auth.json').write_text('{"fake": true}')
        env_patch = mock.patch.dict(os.environ, {'CODEX_HOME': str(fake_account)})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        (self.root / 'agents').mkdir()
        (self.root / 'agents' / 'BOTS.md').write_text('Shared rules')
        (self.root / 'workers').mkdir()
        (self.root / 'static').mkdir()
        (self.root / 'static' / 'index.html').write_text('hub')
        self.h = hub.Hub(self.root, {'agents_dir': 'agents', 'claude_bin': str(FAKE),
            'workers_dir': 'workers', 'media_allowlist': [], 'default_model': 'haiku',
            'max_parallel': 3, 'turn_timeout': 3, 'max_upload_bytes': 10000,
            'chrome_agents': ['inbox'], 'allowed_origins': []})
        self.addCleanup(self.h.close)
        self.h.bootstrap({})
        self.aid = 'assistant'
        self.cid = 'agent:assistant'
        self.reqnum = 0

    def request(self, path, method='GET', data=None, headers=None, raw=False):
        """Drive real Handler.dispatch with HTTP bytes, without forbidden socket bind."""
        h = hub.Handler.__new__(hub.Handler)
        h.server = type('Server', (), {'hub': self.h, 'server_address': ('127.0.0.1', 4700)})()
        h.connection = DummyConnection()
        h.client_address = ('127.0.0.1', 12345)
        h.path = path
        h.requestline = method + ' ' + path + ' HTTP/1.1'
        h.command = method
        h.request_version = 'HTTP/1.1'
        h.close_connection = False
        if data is not None and not raw:
            data = json.dumps(data).encode()
        data = data or b''
        h.rfile = io.BytesIO(data)
        h.wfile = io.BytesIO()
        msg = email.message.Message()
        base = {'Host': '127.0.0.1:4700'}
        if method == 'POST':
            base.update({'Origin': 'http://127.0.0.1:4700', 'X-Hub-Request': '1',
                         'Content-Type': 'application/json', 'Content-Length': str(len(data))})
        base.update(headers or {})
        for k, v in base.items(): msg[k] = v
        h.headers = msg
        h.dispatch(method == 'POST')
        first, _, body = h.wfile.getvalue().partition(b'\r\n\r\n')
        status = int(first.splitlines()[0].split()[1])
        return status, first.decode('latin1'), body

    def login(self):
        status, heads, _ = self.request('/api/login', 'POST', {'token': self.h.initial_token})
        self.assertEqual(status, 200)
        self.assertIn('HttpOnly', heads)
        self.assertIn('SameSite=Strict', heads)
        return heads.split('hub_session=')[1].split(';')[0]

    def api(self, path, method='GET', data=None, **kw):
        cookie = getattr(self, 'cookie', None)
        headers = dict(kw.pop('headers', {}))
        if cookie: headers['Cookie'] = 'hub_session=' + cookie
        return self.request(path, method, data, headers=headers, **kw)

    def send(self, cid=None, text='hello', **extra):
        self.reqnum += 1
        return self.h.send({'request_id': 'request-%08d' % self.reqnum,
                            'chat_id': cid or self.cid, 'text': text, **extra})

    def done(self, jid):
        def completed():
            with self.h.lock:
                return self.h.db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()[0] in ('done', 'error')
        return poll(completed)

    def calls(self, aid='assistant'):
        p = self.root / 'agents' / aid / 'fake_calls.jsonl'
        return [json.loads(s) for s in p.read_text().splitlines()] if p.exists() else []

    def responses(self, aid, rows):
        (self.root / 'agents' / aid / 'fake_responses.json').write_text(json.dumps(rows))

    def test_auth_csrf_host_and_bad_json(self):
        self.assertEqual(self.request('/api/state')[0], 401)
        self.assertEqual(self.request('/api/login', 'POST', {'token': 'wrong'})[0], 401)
        self.cookie = self.login()
        self.assertEqual(self.api('/api/state')[0], 200)
        self.assertEqual(self.api('/api/state', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(self.api('/api/agents', 'POST', {'name': 'X'}, headers={'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.api('/api/agents', 'POST', {'name': 'X'}, headers={'X-Hub-Request': '0'})[0], 403)
        self.assertEqual(self.api('/api/agents', 'POST', b'{oops', raw=True)[0], 400)
        self.assertEqual(self.api('/api/agents', 'POST', b'[]', raw=True)[0], 400)
        self.assertEqual(self.api('/api/logout', 'POST', {})[0], 200)
        self.assertEqual(self.api('/api/state')[0], 401)

    def test_sse_requires_login_emits_change_and_unregisters(self):
        self.assertEqual(self.request('/api/events')[0], 401)
        self.cookie = self.login()
        handler = hub.Handler.__new__(hub.Handler)
        handler.server = type('Server', (), {'hub': self.h, 'server_address': ('127.0.0.1', 4700)})()
        handler.connection = DummyConnection()
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
        worker = threading.Thread(target=handler.dispatch, args=(False,), daemon=True)
        worker.start()
        try:
            poll(lambda: b'event: ready\ndata: {}' in handler.wfile.getvalue())
            self.assertEqual(len(self.h.subscribers), 1)
            self.h.emit('message', self.cid)
            poll(lambda: b'event: change\ndata: {"kind": "message", "chat_id": "agent:assistant"}' in handler.wfile.getvalue())
            response = handler.wfile.getvalue()
            self.assertIn(b'Content-Type: text/event-stream', response)
            self.assertIn(b'Cache-Control: no-store', response)
        finally:
            self.h.stop.set()
            self.h.emit('shutdown')  # Wake queue.get so close does not wait five seconds.
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(self.h.subscribers), 0)

    def test_real_loopback_smoke_if_sandbox_allows(self):
        try:
            server = hub.Server(('127.0.0.1', 0), self.h)
        except PermissionError:
            self.skipTest('sandbox denies loopback socket bind')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
            try:
                conn.request('GET', '/api/state')
                reply = conn.getresponse()
                self.assertEqual(reply.status, 401)
                self.assertIn('Login required', reply.read().decode())
            finally:
                conn.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_agent_creation_and_state(self):
        self.cookie = self.login()
        status, _, data = self.api('/api/agents', 'POST', {'name': 'My Helper', 'role': 'Check facts.', 'model': 'sonnet', 'emoji': '🧪'})
        self.assertEqual(status, 200)
        got = json.loads(data)
        self.assertEqual(got['chat_id'], 'agent:my-helper')
        folder = self.root / 'agents' / 'my-helper'
        self.assertNotIn('@' + str(self.root / 'agents' / 'BOTS.md'), (folder / 'CLAUDE.md').read_text())
        self.assertFalse(got['agent']['use_global_rules'])
        self.assertEqual(json.loads((folder / '.claude' / 'settings.json').read_text())['model'], 'sonnet')
        state = json.loads(self.api('/api/state')[2])
        self.assertIn('agent:my-helper', [c['id'] for c in state['chats']])
        self.assertEqual(self.api('/api/agents', 'POST', {'name': 'My Helper', 'role': 'x'})[0], 409)

    def test_authenticated_chat_route_and_static_pwa_assets(self):
        self.cookie = self.login()
        status, _, data = self.api('/api/message', 'POST', {'chat_id': self.cid,
            'text': 'hello through HTTP', 'request_id': 'http-message-001'})
        self.assertEqual(status, 200)
        self.done(json.loads(data)['job_id'])
        history = json.loads(self.api('/api/chat?id=' + quote(self.cid))[2])
        self.assertEqual(history['messages'][-1]['text'], 'echo: hello through HTTP')
        for name in ('app.js', 'style.css', 'sw.js', 'manifest.json', 'icon-192.png', 'icon-512.png'):
            (self.root / 'static' / name).write_bytes((hub.ROOT / 'static' / name).read_bytes())
        for route in ('/', '/manifest.json', '/sw.js', '/static/app.js', '/static/style.css', '/static/icon-192.png'):
            self.assertEqual(self.request(route)[0], 200, route)
        self.assertIn('Service-Worker-Allowed: /', self.request('/sw.js')[1])
        self.assertEqual(self.request('/static/../hub.py')[0], 404)

    def test_external_agents_discovered_untouched_and_new_agents_local(self):
        external = self.root / 'external-bots'
        external.mkdir()
        (external / 'BOTS.md').write_text('Keep review gates.')
        for name in ('clients', 'inbox', 'ops', 'builder', 'personal', 'approvals'):
            p = external / name
            p.mkdir()
            (p / 'CLAUDE.md').write_text('# ' + name)
        before = {str(p): p.read_bytes() for p in external.rglob('*') if p.is_file()}
        app_root = self.root / 'isolated-hub'
        app_root.mkdir()
        other = hub.Hub(app_root, {'agents_dir': str(external), 'claude_bin': str(FAKE)})
        try:
            self.assertEqual(len(other.agents()), 7)
            self.assertTrue(other.agents()['guide']['guide'])
            other.create_agent({'name': 'Researcher', 'role': 'Research carefully.', 'model': 'haiku'})
            self.assertTrue((app_root / 'agents' / 'researcher' / 'NOTES.md').is_file())
            self.assertNotIn('@' + str(external / 'BOTS.md'), (app_root / 'agents' / 'researcher' / 'CLAUDE.md').read_text())
            self.assertTrue(other.agents()['inbox']['use_global_rules'])
            hidden = other.archive({'kind': 'agent', 'id': 'inbox'})
            self.assertTrue(hidden['external_hidden'])
            self.assertNotIn('inbox', other.agents())
            self.assertEqual(before, {str(p): p.read_bytes() for p in external.rglob('*') if p.is_file()})
        finally:
            other.close()

    def test_direct_cli_arguments_sessions_rotation_and_reset(self):
        for i in range(16):
            jid = self.send(text='turn %d' % i)['job_id']
            self.done(jid)
        calls = self.calls()
        self.assertEqual(len(calls), 16)
        self.assertEqual(calls[0]['cwd'], str(self.root / 'agents' / self.aid))
        self.assertEqual(calls[0]['argv'][0:2], ['-p', 'turn 0'])
        self.assertIn('--permission-mode', calls[0]['argv'])
        self.assertIn('--model', calls[0]['argv'])
        self.assertNotIn('--resume', calls[0]['argv'])
        self.assertEqual(calls[1]['argv'][calls[1]['argv'].index('--resume')+1], 'fake-1')
        self.assertNotIn('--resume', calls[15]['argv'])
        with self.h.lock:
            self.h.db.execute('UPDATE sessions SET t=? WHERE chat_id=?', (time.time()-10801, self.cid))
            self.h.db.commit()
        self.done(self.send(text='after idle')['job_id'])
        self.assertNotIn('--resume', self.calls()[-1]['argv'])

    def test_inbox_chrome_flag_and_invalid_cli_json(self):
        self.h.create_agent({'name': 'Inbox', 'role': 'Handle inbox.', 'model': 'haiku', 'use_global_rules': True,
                             'chrome': True})
        self.responses('inbox', [{'invalid_json': True}])
        jid = self.send('agent:inbox', 'check')['job_id']
        self.done(jid)
        call = self.calls('inbox')[0]
        self.assertIn('--chrome', call['argv'])
        row = self.h.db.execute('SELECT status,error FROM jobs WHERE id=?', (jid,)).fetchone()
        self.assertEqual(row['status'], 'error')
        self.assertIn('invalid JSON', row['error'])

    def test_card_parser_only_extracts_valid_standalone_lines(self):
        valid = 'CARD: '+json.dumps({'title': 'Review', 'actions': ['Approve']})
        malformed = 'CARD: '+json.dumps({'title': '', 'actions': ['Approve']})
        clean, cards = hub.parse_cards('intro\n'+malformed+'\n'+valid+'\noutro')
        self.assertEqual(len(cards), 1)
        self.assertIn(malformed, clean)
        self.assertNotIn(valid, clean)
        reset = self.send(text='/new')
        self.assertIsNone(reset['job_id'])
        self.done(self.send(text='new turn')['job_id'])
        self.assertNotIn('--resume', self.calls()[-1]['argv'])

    def test_queue_order_error_and_card_approval_once(self):
        card = 'CARD: '+json.dumps({'title': 'Send draft', 'text': 'Reviewed', 'actions': ['Approve', 'Skip']})
        self.responses(self.aid, [{'sleep': .08, 'result': 'first\n' + card}, {'result': 'second'}, {'exit': 2, 'stderr': 'fake failed'}])
        jobs = [self.send(text=t)['job_id'] for t in ('one', 'two', 'three')]
        for jid in jobs: self.done(jid)
        self.assertEqual([c['argv'][1] for c in self.calls()], ['one', 'two', 'three'])
        self.assertEqual([self.h.db.execute('SELECT status FROM jobs WHERE id=?', (j,)).fetchone()[0] for j in jobs], ['done', 'done', 'error'])
        hist = self.h.history(self.cid)['messages']
        assistant = next(m for m in hist if m['role'] == 'assistant' and m['cards'])
        self.assertEqual(assistant['text'], 'first')
        self.assertEqual(assistant['cards'][0]['title'], 'Send draft')
        self.reqnum += 1
        payload = {'chat_id': self.cid, 'request_id': 'card-%08d' % self.reqnum, 'message_id': assistant['id'], 'index': 0, 'action': 'Approve'}
        approved = self.h.send(payload, card=True)
        self.assertEqual(self.h.send(payload, card=True)['duplicate'], True)
        payload['request_id'] = 'different-approval'
        with self.assertRaises(hub.HubError) as cm: self.h.send(payload, card=True)
        self.assertEqual(cm.exception.status, 409)
        self.done(approved['job_id'])
        self.assertEqual(sum(m['text'] == 'Approve: Send draft' for m in self.h.history(self.cid)['messages']), 1)

    def test_group_routing_reply_and_global_handoff_budget(self):
        for name in ('Alpha', 'Beta', 'Gamma'):
            self.h.create_agent({'name': name, 'role': 'Test', 'model': 'haiku', 'draft_only': True})
        group = self.h.group({'name': 'Team', 'agents': ['alpha', 'beta', 'gamma']})['chat']['id']
        self.responses('alpha', [{'result': 'Starting the answer.\n@@handoff beta: task one'}])
        self.responses('beta', [{'result': '@@handoff gamma: nested request'}, {'result': 'done'}])
        self.responses('gamma', [{'result': '@@handoff beta: last request'}])
        jid = self.send(group, '@alpha start')['job_id']
        self.done(jid)
        self.assertEqual(sum(len(self.calls(a)) for a in ('alpha', 'beta', 'gamma')), 4)
        hist = self.h.history(group)['messages']
        first = next(m for m in hist if m['role'] == 'assistant')
        self.done(self.send(group, 'follow up', reply_to=first['id'])['job_id'])
        self.assertEqual(len(self.calls('alpha')), 2)
        with mock.patch('hub.cli_choice', return_value=None):
            routed = self.send(group, 'unrouted')
        self.assertEqual(routed['routing']['kind'], 'tie')
        self.done(routed['job_id'])

    def test_upload_files_ranges_and_escape_guards(self):
        self.cookie = self.login()
        payload = b'0123456789'
        status, _, out = self.api('/api/upload?name=sample.mp4', 'POST', payload, raw=True,
                                  headers={'Content-Type': 'application/octet-stream'})
        self.assertEqual(status, 200)
        path = json.loads(out)['path']
        for rng, expect, code in [('bytes=2-4', b'234', 206), ('bytes=7-', b'789', 206),
                                   ('bytes=-3', b'789', 206), ('bytes=50-', b'', 416)]:
            status, head, body = self.api('/api/file?path=' + quote(path), headers={'Range': rng})
            self.assertEqual(status, code)
            if code == 206:
                self.assertEqual(body, expect)
                self.assertIn('Accept-Ranges: bytes', head)
                self.assertIn('Content-Range: bytes ', head)
            else: self.assertIn('Content-Range: bytes */10', head)
        secret = self.root / 'secret.txt'
        secret.write_text('secret')
        link = self.h.uploads / 'escape.mp4'
        link.symlink_to(secret)
        self.assertEqual(self.api('/api/file?path=' + quote(str(link)))[0], 403)
        self.assertEqual(self.api('/api/file?path=' + quote(str(self.h.uploads / '..' / 'secret.txt')))[0], 403)
        credentials = self.root / 'agents' / self.aid / 'credentials.json'
        credentials.write_text('{"secret":"do not serve"}')
        self.assertEqual(self.api('/api/file?path=' + quote(str(credentials)))[0], 403)
        video = self.root / 'agents' / self.aid / 'demo clip.mp4'
        video.write_bytes(payload)
        self.assertEqual(self.h.extract_media('Watch ' + str(video))[0]['path'], str(video))
        status, head, body = self.api('/api/file?path=' + quote(str(video)), method='HEAD')
        self.assertEqual(status, 200)
        self.assertEqual(body, b'')
        self.assertIn('Content-Length: 10', head)

    def test_restart_marks_uncertain_jobs_without_replay(self):
        with self.h.lock:
            self.h.sync_chats()
            self.h.db.execute("INSERT INTO jobs(chat_id,agent_id,prompt,status,created) VALUES(?,?,?,?,?)", (self.cid, self.aid, 'unsafe', 'queued', time.time()))
            self.h.db.commit()
        self.h.close()
        old = self.h
        self.h = hub.Hub(self.root, old.config)
        self.addCleanup(self.h.close)
        row = self.h.db.execute('SELECT status,error FROM jobs').fetchone()
        self.assertEqual(row['status'], 'interrupted')
        self.assertIn('inspect outcome', row['error'])
        self.assertEqual(self.calls(), [])

    def test_worker_plain_pid_and_done_schema_read_only(self):
        root = self.root / 'workers'
        (root / (str(os.getpid()) + '.lock')).write_text('A real task')
        (root / '99999999.lock').write_text('Gone')
        before = {p.name: p.read_bytes() for p in root.iterdir()}
        media = self.h.uploads / 'image.png'
        media.write_bytes(b'PNG')
        (root / 'done.jsonl').write_text(json.dumps({'message': 'FILE: ' + str(media), 'files': [{'file': str(media)}], 'task': 'done'})+'\n')
        before = {p.name: p.read_bytes() for p in root.iterdir()}
        got = self.h.workers()
        self.assertEqual({w['status'] for w in got['running']}, {'running', 'stale'})
        self.assertEqual(len(got['done']), 1)
        self.assertEqual(got['done'][0]['files'][0]['path'], str(media))
        self.assertIn('id', got['done'][0])
        self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})


if __name__ == '__main__': unittest.main()
