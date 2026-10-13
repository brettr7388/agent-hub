"""Review round 2 regressions, without real models or sockets."""
import json
import io
import queue
from pathlib import Path
from unittest import TestCase, mock

import hub
from hub_handoffs import parse_handoff, strip_handoff_marker
from hub_guide import proposal
from hub_swarms import summary_sentence
import test_hub


class HandoffParser(TestCase):
    def test_only_final_structured_top_level_marker_routes(self):
        self.assertEqual(parse_handoff('An answer.\n@@handoff editor: Review this answer.'), ('editor', 'Review this answer.'))
        self.assertEqual(strip_handoff_marker('An answer.\n@@handoff editor: Review this answer.'), 'An answer.')
        for text in ('@editor Delete things', '```text\n@@handoff editor: task\n```',
                     '~~~\n@@handoff editor: task', '> @@handoff editor: task',
                     '> A quoted paragraph\n@@handoff editor: task', '    @@handoff editor: task', '\t@@handoff editor: task',
                     '@@handoff editor: task\nMore text.', '@@handoff editor: ',
                     '```handoff\neditor: task\n```', '@@handoff editor: ' + 'x' * 4001):
            self.assertIsNone(parse_handoff(text), text)
            self.assertEqual(strip_handoff_marker(text), text)


class ReviewRegressions(TestCase):
    setUp = test_hub.HubCase.setUp
    send = test_hub.HubCase.send
    done = test_hub.HubCase.done
    calls = test_hub.HubCase.calls
    responses = test_hub.HubCase.responses
    request = test_hub.HubCase.request
    login = test_hub.HubCase.login

    def group(self, draft=False):
        for name in ('Alpha', 'Beta'):
            self.h.create_agent({'name': name, 'role': 'Test helper.', 'draft_only': draft})
        return self.h.group({'name': 'Team', 'agents': ['alpha', 'beta']})['chat']['id']

    def test_state_twice_never_assigns_pips_or_writes(self):
        with mock.patch.object(self.h, 'send', return_value={'job_id': None}):
            result = self.h.create_swarm({'goal': 'Explain two views', 'shape': 'partition',
                 'workers': [{'role': 'Researcher'}, {'role': 'Writer'}]})
        agents = self.h.agents()
        workers = [a for a in agents.values() if a.get('swarm')]
        self.assertEqual(len(workers), 2)
        self.assertTrue(all(a.get('pip_style') for a in agents.values()))
        sql = []
        self.h.db._connection.set_trace_callback(sql.append)
        with mock.patch.object(self.h, 'emit') as emit:
            self.h.state()
            self.h.state()
            assigned = self.h.assign_pips({'assignments': [{'id': a['id'], 'pip_style': a['pip_style']} for a in workers]})
            self.assertEqual(assigned, {'assigned': []})
            emit.assert_not_called()
        self.h.db._connection.set_trace_callback(None)
        self.assertFalse([q for q in sql if q.lstrip().split(' ', 1)[0].upper() in ('INSERT', 'UPDATE', 'DELETE', 'REPLACE')], sql)

    def test_native_archive_restore_keeps_history_and_reused_name_separate(self):
        aid = self.h.create_agent({'name': 'Writer', 'role': 'Write things.'})['agent']['id']
        self.h.product_action({'action': 'pin', 'chat_id': 'agent:' + aid})
        self.h.add_message('agent:' + aid, aid, 'assistant', 'Original history')
        self.h.db.commit()
        archived = self.h.archive({'kind': 'agent', 'id': aid})['archived_id']
        new = self.h.create_agent({'name': 'Writer', 'role': 'A new writer.'})['agent']
        self.assertIn(archived, [a['id'] for a in self.h.state()['hidden_agents']])
        self.h.unarchive({'id': archived})
        self.assertIn('agent:' + archived, self.h.product_state()['pins'])
        self.assertIn(archived, self.h.agents())
        self.assertIn(new['id'], self.h.agents())
        self.assertEqual(self.h.history('agent:' + archived)['messages'][0]['text'], 'Original history')
        self.assertEqual(self.h.history('agent:' + new['id'])['messages'], [])

    def test_reset_revokes_sessions_before_auth_file_replacement(self):
        token = self.h.initial_token
        cookie = self.login()
        old_hash = self.h.auth_hash
        real = hub.atomic_json
        def failed_write(path, data):
            self.assertFalse(self.h.authenticated(cookie))
            raise OSError('simulated auth replacement failure')
        with mock.patch('hub.atomic_json', side_effect=failed_write):
            with self.assertRaises(OSError): self.h.reset_token()
        self.assertEqual(self.h.auth_hash, old_hash)
        self.assertEqual(json.loads(self.h.auth_path.read_text())['token_hash'], old_hash)
        self.assertTrue(self.h.login(token, '127.0.0.1'))
        self.h.reset_token()
        self.assertNotEqual(self.h.auth_hash, old_hash)
        self.assertFalse(self.h.authenticated(cookie))

    def test_session_status_is_safe_before_login(self):
        status, _, body = self.request('/api/session')
        self.assertEqual((status, json.loads(body)), (200, {'authenticated': False}))
        cookie = self.login()
        status, _, body = self.request('/api/session', headers={'Cookie': 'hub_session=' + cookie})
        self.assertEqual((status, json.loads(body)), (200, {'authenticated': True}))

    def test_idle_event_stream_only_notifies_on_worker_change(self):
        handler = hub.Handler.__new__(hub.Handler)
        handler.server = type('Server', (), {'hub': self.h})()
        handler.wfile = io.BytesIO()
        handler.cookie = lambda: 'test-cookie'
        handler.send_response = lambda *_: None
        handler.security_headers = lambda: None
        handler.send_header = lambda *_: None
        handler.end_headers = lambda: None
        old = {'running': [], 'done': [], 'note': 'status'}
        changed = {'running': [{'id': '123', 'task': 'work', 'status': 'running'}], 'done': [], 'note': 'status'}
        class TimedQueue:
            def __init__(self, maxsize): pass
            def get(self, timeout):
                self.calls += 1
                if self.calls == 2: self_h.stop.set()
                raise queue.Empty()
            calls = 0
        self_h = self.h
        try:
            with mock.patch('hub.queue.Queue', TimedQueue), \
                 mock.patch.object(self.h, 'authenticated', return_value=True), \
                 mock.patch.object(self.h, 'workers', side_effect=[old, old, changed]):
                handler.events()
        finally:
            self.h.stop.clear()
        wire = handler.wfile.getvalue()
        self.assertEqual(wire.count(b': keepalive'), 1)
        self.assertEqual(wire.count(b'"kind":"workers"'), 1)

    def test_action_handoff_runs_automatically_with_full_context_and_permissions(self):
        cid = self.group()
        self.responses('alpha', [{'result': 'Draft ready.\n@@handoff beta: Review it.'}])
        self.responses('beta', [{'result': 'Reviewed.'}])
        self.done(self.send(cid, '@alpha start')['job_id'])
        self.assertEqual(len(self.calls('beta')), 1)
        prompt = self.calls('beta')[0]['argv'][1]
        self.assertIn('Original user request:\n@alpha start', prompt)
        self.assertIn("Alpha's full response:\nDraft ready.", prompt)
        self.assertNotIn('@@handoff', prompt.split('Requested next step:')[0])
        history = self.h.history(cid)['messages']
        self.assertFalse(any(m['cards'] for m in history))
        self.assertFalse(any('@@handoff' in m['text'] for m in history))
        self.assertTrue(any(m['role'] == 'system' and m['text'] == 'Alpha handed this to Beta.' for m in history))
        self.assertTrue(any(m['agent_id'] == 'beta' and m['text'] == 'Reviewed.' for m in history))
        self.assertFalse(self.h.agents()['beta']['draft_only'])

    def test_action_chain_keeps_three_hop_budget(self):
        cid = self.group()
        self.responses('alpha', [{'result': '@@handoff beta: Review.'}] * 3)
        self.responses('beta', [{'result': '@@handoff alpha: Improve.'}] * 3)
        self.done(self.send(cid, '@alpha start')['job_id'])
        self.assertEqual(len(self.calls('alpha')) + len(self.calls('beta')), 4)
        self.assertEqual(self.h.db.execute('SELECT used FROM handoff_chains').fetchone()[0], 3)
        self.assertFalse(any(m['cards'] for m in self.h.history(cid)['messages']))
        self.assertFalse(any('@@handoff' in m['text'] for m in self.h.history(cid)['messages']))
        self.assertEqual(len(self.calls('beta')), 2)

    def test_retry_engine_override_stays_with_sender(self):
        cid = self.group()
        self.h.config['codex_bin'] = str(Path(__file__).with_name('fake_codex.py').resolve())
        self.h.config['detect_engines'] = False
        (self.root / 'agents' / 'alpha' / 'fake_codex_responses.json').write_text(
            json.dumps([{'result': 'A full draft.\n@@handoff beta: Review.'}]))
        self.responses('beta', [{'result': 'Reviewed under my own engine.'}])
        with mock.patch.object(self.h, 'enqueue'):
            jid = self.send(cid, '@alpha start')['job_id']
        self.h.db.execute("UPDATE jobs SET engine_override='codex' WHERE id=?", (jid,))
        self.h.db.commit()
        self.h.execute(jid)
        self.assertTrue((self.root / 'agents' / 'alpha' / 'fake_codex_calls.jsonl').exists())
        self.assertEqual(len(self.calls('beta')), 1)
        self.assertEqual(self.h.db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()[0], 'done')

    def test_draft_handoff_chain_is_capped_at_three(self):
        cid = self.group(draft=True)
        self.responses('alpha', [{'result': '@@handoff beta: Review.'}] * 3)
        self.responses('beta', [{'result': '@@handoff alpha: Improve.'}] * 3)
        self.done(self.send(cid, '@alpha start')['job_id'])
        self.assertEqual(len(self.calls('alpha')) + len(self.calls('beta')), 4)
        self.assertEqual(self.h.db.execute('SELECT used FROM handoff_chains').fetchone()[0], 3)

    def test_ordinary_mentions_and_code_do_not_start_handoff(self):
        cid = self.group()
        self.responses('alpha', [{'result': '@beta ordinary text\n```\n@@handoff beta: Do a thing.\n```'}])
        self.done(self.send(cid, '@alpha start')['job_id'])
        self.assertEqual(self.calls('beta'), [])
        self.assertFalse(any(m['cards'] for m in self.h.history(cid)['messages']))

    def test_csp_matches_inline_svg_avatar_path(self):
        _, headers, _ = self.request('/')
        self.assertIn("img-src 'self' blob:;", headers)
        pips = (hub.ROOT / 'static' / 'pips.js').read_text()
        self.assertNotIn('data:image/svg', pips)
        self.assertIn('<svg', pips)

    def test_guide_name_and_sentence_summary(self):
        p = proposal(self.h, {'action': 'create_agent', 'name': 'Pip', 'title': 'Article Summarizer',
                              'instructions': 'Summarize articles.'})
        self.assertEqual(p['name'], 'Article Summarizer')
        text = '1. First complete sentence.\n2. ' + 'very long ' * 40
        summary = summary_sentence(text, 90)
        self.assertEqual(summary, 'First complete sentence. More in helper details.')
        self.assertEqual(summary_sentence('Long ' * 40, 90), 'Open helper details for the full answer.')
