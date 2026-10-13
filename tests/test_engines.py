"""Engine switching and CLI behavior with fake local executables only."""
import json
from pathlib import Path
import unittest
from unittest import mock
import subprocess
import hub
import test_hub
from test_hub import poll

FAKE_CODEX = Path(__file__).with_name('fake_codex.py').resolve()


class EngineCase(unittest.TestCase):
    send = test_hub.HubCase.send
    done = test_hub.HubCase.done
    login = test_hub.HubCase.login
    api = test_hub.HubCase.api
    request = test_hub.HubCase.request

    def setUp(self):
        test_hub.HubCase.setUp(self)
        self.h.config['codex_bin'] = str(FAKE_CODEX)
        self.h.config['detect_engines'] = False

    def codex_calls(self, aid='coder'):
        p = self.root / 'agents' / aid / 'fake_codex_calls.jsonl'
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def test_bootstrap_and_safe_setup_status(self):
        agents = self.h.agents()
        self.assertEqual({'guide', 'assistant', 'researcher', 'reviewer'}, set(agents))
        self.assertIn('demo team', [c['name'].lower() for c in self.h.state()['chats']])
        setup = self.h.setup_status()
        self.assertEqual(setup['default_engine'], 'claude')
        self.assertEqual(setup['engines']['claude']['authenticated'], 'unknown')
        self.assertNotIn('token', json.dumps(setup))

    def test_codex_new_resume_and_last_message_file(self):
        self.h.create_agent({'name': 'Coder', 'role': 'Code.', 'engine': 'codex', 'model': 'gpt-6.1-sol', 'title': 'Engineer'})
        p = self.root / 'agents' / 'coder'
        (p / 'fake_codex_responses.json').write_text(json.dumps([{'result': 'event response', 'last': 'first answer', 'thread_id': 'thread-1'}, {'result': 'second answer', 'thread_id': 'thread-1'}]))
        one = self.send('agent:coder', 'build')['job_id']
        self.done(one)
        two = self.send('agent:coder', 'refine')['job_id']
        self.done(two)
        calls = self.codex_calls()
        self.assertEqual(calls[0]['argv'][:2], ['exec', '--json'])
        self.assertEqual(calls[1]['argv'][:4], ['exec', 'resume', 'thread-1', '--json'])
        replies = [m['text'] for m in self.h.history('agent:coder')['messages'] if m['role'] == 'assistant']
        self.assertEqual(replies, ['first answer', 'second answer'])
        self.assertEqual(self.h.agents()['coder']['title'], 'Engineer')

    def test_engine_mismatch_does_not_resume(self):
        self.h.create_agent({'name': 'Coder', 'role': 'Code.', 'engine': 'codex'})
        self.done(self.send('agent:coder', 'one')['job_id'])
        with self.h.lock:
            self.h.db.execute("UPDATE sessions SET engine='claude' WHERE agent_id='coder'")
            self.h.db.commit()
        self.done(self.send('agent:coder', 'two')['job_id'])
        self.assertNotIn('resume', self.codex_calls()[-1]['argv'])

    def test_edit_agent_model_resets_sessions_and_rejects_invalid_changes(self):
        created = self.h.create_agent({'name': 'Coder', 'role': 'Code.', 'engine': 'codex', 'model': 'gpt-6.1-sol'})
        aid = created['agent']['id']
        with self.h.lock:
            self.h.db.execute('INSERT INTO sessions(chat_id,agent_id,sid,t,turns,engine,model) VALUES(?,?,?,?,?,?,?)',
                              ('agent:coder', aid, 'old-thread', 1, 1, 'codex', 'gpt-6.1-sol'))
            self.h.db.commit()
        (self.root / 'agents' / aid / '.claude' / 'settings.json').write_text(json.dumps({'permissions': {'allow': ['Read']}}))
        updated = self.h.edit_agent({'id': aid, 'engine': 'claude', 'model': 'haiku'})['agent']
        self.assertEqual((updated['engine'], updated['model']), ('claude', 'haiku'))
        self.assertIsNone(self.h.db.execute('SELECT 1 FROM sessions WHERE agent_id=?', (aid,)).fetchone())
        settings = json.loads((self.root / 'agents' / aid / '.claude' / 'settings.json').read_text())
        self.assertEqual(settings['model'], 'haiku')
        self.assertEqual(settings['permissions']['allow'], ['Read'])
        with self.assertRaises(hub.HubError) as error:
            self.h.edit_agent({'id': aid, 'engine': 'claude', 'model': 'not-a-model'})
        self.assertEqual(error.exception.status, 400)
        with self.assertRaises(hub.HubError):
            self.h.edit_agent({'id': aid, 'engine': 'codex', 'model': 'bad model'})
        self.assertEqual(self.h.agents()[aid]['model'], 'haiku')

    def test_probes_prefer_logged_in_engine_without_exposing_output(self):
        self.h.config['detect_engines'] = True
        def probe(args, **kwargs):
            self.assertEqual(kwargs['timeout'], 5)
            self.assertNotIn('stdout', kwargs)
            return subprocess.CompletedProcess(args, 0 if args[1:3] == ['login', 'status'] else 1)
        with mock.patch('hub.run_bounded', side_effect=probe):
            result = self.h.probe_engines()
        self.assertEqual(result['claude']['authenticated'], 'login_required')
        self.assertEqual(result['codex']['authenticated'], 'ready')
        self.assertEqual(self.h.default_engine(), 'codex')

    def test_codex_failure_event_cannot_be_reported_as_success(self):
        final = self.root / 'last.txt'
        final.write_text('partial answer')
        events = '\n'.join(json.dumps(value) for value in [
            {'type':'item.completed','item':{'type':'agent_message','text':'partial'}},
            {'type':'turn.failed','error':{'message':'rate limited'}}])
        with self.assertRaises(RuntimeError): self.h.parse_codex(events, final)

    def test_stop_only_selected_job(self):
        self.h.create_agent({'name': 'Coder', 'role': 'Code.', 'engine': 'codex'})
        p = self.root / 'agents' / 'coder'
        (p / 'fake_codex_responses.json').write_text(json.dumps([{'sleep': 2}]))
        jid = self.send('agent:coder', 'long')['job_id']
        poll(lambda: jid in self.h.job_processes)
        self.h.stop_job({'job_id': jid})
        poll(lambda: self.h.db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()[0] == 'stopped')
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM jobs WHERE status="stopped"').fetchone()[0], 1)


if __name__ == '__main__': unittest.main()
