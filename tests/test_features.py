"""Feature checks use fake CLIs, disposable plists and a fake loopback approvals service."""
import datetime as dt
import io
import json
import plistlib
import subprocess
import sys
import threading
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
import hub
from hub_features import next_run
import test_hub


class FeaturesCase(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    request = test_hub.HubCase.request
    login = test_hub.HubCase.login
    api = test_hub.HubCase.api
    done = test_hub.HubCase.done
    responses = test_hub.HubCase.responses

    def test_script_mode_preserves_feature_error_identity(self):
        source = str(hub.ROOT / 'hub.py')
        script = "from pathlib import Path; __file__ = " + repr(source) + "; exec(Path(__file__).read_text().rsplit(\"\\nif __name__ == '__main__':\", 1)[0]); from hub_features import fail; \ntry: fail(409, 'held')\nexcept HubError as exc: assert exc.status == 409\nelse: raise AssertionError('missing error')"
        result = subprocess.run([sys.executable, '-B', '-c', script], cwd=hub.ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_auth_on_every_new_endpoint(self):
        for path in ('/api/setup', '/api/settings', '/api/jobs', '/api/routines', '/api/approvals/workspace', '/api/swarms', '/api/swarm?id=missing'):
            self.assertEqual(self.request(path)[0], 401, path)
        for path in ('/api/setup', '/api/settings', '/api/jobs/stop', '/api/routines', '/api/routines/toggle', '/api/approvals/review', '/api/swarms', '/api/swarms/action'):
            self.assertEqual(self.request(path, 'POST', {})[0], 401, path)
        self.cookie = self.login()
        for path in ('/api/setup', '/api/settings', '/api/jobs', '/api/routines', '/api/swarms'):
            self.assertEqual(self.api(path)[0], 200, path)
        for path in ('/api/setup', '/api/settings', '/api/jobs/stop', '/api/routines', '/api/routines/toggle', '/api/approvals/review', '/api/swarms', '/api/swarms/action'):
            self.assertEqual(self.api(path, 'POST', {}, headers={'Origin': 'https://evil.example'})[0], 403, path)

    def test_role_settings_persist_and_approvals_loopback_only(self):
        got = self.h.save_settings({'role_models': {'worker': {'engine': 'codex', 'model': 'test-model'}}, 'approvals_url': 'http://localhost:4100'})
        self.assertEqual(got['role_models']['worker']['engine'], 'codex')
        self.assertEqual(json.loads((self.root/'config.json').read_text())['role_models']['worker']['model'], 'test-model')
        for url in ('https://example.com', 'http://localhost:4100/path', 'http://user:secret@localhost:4100', 'http://127.0.0.1:4100?x=1'):
            with self.assertRaises(hub.HubError) as error: self.h.save_settings({'approvals_url': url})
            self.assertIn('http://127.0.0.1:PORT', error.exception.message)
            self.assertNotIn('localhost:4100', error.exception.message)
        self.h.save_settings({'approvals_url': None})
        with self.assertRaises(hub.HubError) as error: self.h.approvals_request('/api/approvals/workspace')
        self.assertEqual(error.exception.status, 409)

    def test_schedule_clock_and_silent_once(self):
        now = dt.datetime(2026, 10, 12, 8, 0).timestamp()
        self.h.clock = lambda: now
        body = {'agent_id': 'assistant', 'name': 'Check', 'prompt': 'Inspect local notes.', 'trigger': 'interval', 'minutes': 5}
        routine = self.h.create_routine(body)['routine']
        self.assertEqual(routine['next_run'], now + 300)
        self.assertIn('Routine created', self.h.history('agent:assistant')['messages'][-1]['text'])
        self.responses('assistant', [{'result': 'SILENT'}])
        self.assertEqual(self.h.tick_routines(now+299), 0)
        self.assertEqual(self.h.tick_routines(now+300), 1)
        jid = self.h.db.execute('SELECT job_id FROM routine_runs').fetchone()[0]
        self.done(jid)
        self.assertFalse(any(m['role'] == 'assistant' and m['text'] == 'SILENT' for m in self.h.history('agent:assistant')['messages']))
        self.assertEqual(self.h.tick_routines(now+300), 0)
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM jobs').fetchone()[0], 1)
        self.h.toggle_routine({'id': routine['id'], 'enabled': False})
        self.assertEqual(self.h.tick_routines(now+9999), 0)

    def test_calendar_triggers_and_readonly_plists(self):
        friday = dt.datetime(2026, 10, 16, 10, 0).timestamp()
        self.assertEqual(dt.datetime.fromtimestamp(next_run({'trigger':'weekdays','time':'09:00'}, friday)).weekday(), 0)
        self.assertEqual(dt.datetime.fromtimestamp(next_run({'trigger':'weekly','time':'09:00','weekday':2}, friday)).weekday(), 2)
        self.assertEqual(dt.datetime.fromtimestamp(next_run({'trigger':'daily','time':'09:00'}, friday)).day, 17)
        folder = self.root/'launchagents'
        folder.mkdir()
        path = folder/'com.example.agent.ops.daily.plist'
        data = plistlib.dumps({'Label':path.stem,'StartCalendarInterval':{'Hour':9,'Minute':0},'ProgramArguments':['python3','routine.py','--bot','ops']})
        path.write_bytes(data)
        self.h.config['launch_agents_dir'] = str(folder)
        self.h.config['external_routine_glob'] = 'com.example.agent.*.plist'
        rows = self.h.routines()['external']
        self.assertEqual(rows[0]['bot'], 'ops')
        self.assertTrue(rows[0]['read_only'])
        self.assertEqual(path.read_bytes(), data)

    def test_hold_text_and_no_redirect_or_proxy(self):
        self.h.config['approvals_url'] = 'http://localhost:4100'
        error = HTTPError('http://localhost:4100/api/approvals/review', 409, 'Hold', {}, io.BytesIO(b'{"error":"HOLD: exact review required"}'))
        with mock.patch('hub_features.urllib.request.OpenerDirector.open', side_effect=error):
            with self.assertRaises(hub.HubError) as held:
                self.h.approvals_review({'id':'draft1','action':'approve'})
        self.assertEqual(held.exception.message, 'HOLD: exact review required')
        for body in ({'id':'x','action':'publish'}, {'id':'x','action':'edit','text':''}):
            with self.assertRaises(hub.HubError): self.h.approvals_review(body)

    def test_approvals_fake_http_server_approve_deny_edit(self):
        seen = []
        class Fake(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(200); self.end_headers()
                self.wfile.write(b'{"timely":[{"id":"d1","text":"Draft"}]}')
            def do_POST(self):
                value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append((self.path, value))
                hold = value['id'] == 'held'
                self.send_response(409 if hold else 200); self.end_headers()
                self.wfile.write(b'{"error":"HOLD: waiting for review"}' if hold else b'{"ok":true}')
        try: server = ThreadingHTTPServer(('127.0.0.1',0), Fake)
        except PermissionError: self.skipTest('sandbox denies loopback bind; adapter/hold unit checks still run')
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            self.h.config['approvals_url'] = 'http://127.0.0.1:%s' % server.server_port
            self.assertEqual(self.h.approvals_request('/api/approvals/workspace')['timely'][0]['id'], 'd1')
            for payload in ({'id':'d1','action':'approve'}, {'id':'d2','action':'deny','reason':'Skip'}, {'id':'d3','action':'edit','text':'Revised'}):
                self.assertTrue(self.h.approvals_review(payload)['ok'])
                self.assertEqual(seen[-1], ('/api/approvals/review',payload))
            with self.assertRaises(hub.HubError) as held: self.h.approvals_review({'id':'held','action':'approve'})
            self.assertEqual(held.exception.message, 'HOLD: waiting for review')
        finally:
            server.shutdown(); server.server_close(); thread.join(2)

if __name__ == '__main__': unittest.main()
