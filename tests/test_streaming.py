"""Incremental CLI replies, failure and cancellation, without model calls."""
import json
from pathlib import Path
import queue
import subprocess
import sys
import unittest
from unittest import mock

import test_hub
from test_hub import poll


class StreamingCase(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    send = test_hub.HubCase.send
    done = test_hub.HubCase.done

    def prepare(self, engine, choice):
        aid = 'stream-' + engine
        self.h.config['codex_bin'] = str(Path(__file__).with_name('fake_codex.py').resolve())
        made = self.h.create_agent({'name': aid, 'role': 'Answer.', 'engine': engine})
        filename = 'fake_responses.json' if engine == 'claude' else 'fake_codex_responses.json'
        (self.root / 'agents' / aid / filename).write_text(json.dumps([choice]))
        events = queue.Queue()
        with self.h.lock:
            self.h.subscribers.add(events)
        self.addCleanup(self.h.subscribers.discard, events)
        return aid, made['chat_id'], events

    def partial(self, events):
        while True:
            event = events.get(timeout=5)
            if event['kind'] == 'delta':
                return event

    def test_both_engines_partial_then_authoritative_final_and_session(self):
        for engine in ('claude', 'codex'):
            with self.subTest(engine=engine):
                aid, cid, events = self.prepare(engine, {'stream': ['First ', 'draft'],
                    'stream_delay': .3, 'result': 'Final answer', 'session_id': 'claude-session',
                    'thread_id': 'codex-session'})
                jid = self.send(cid, 'Answer now')['job_id']
                delta = self.partial(events)
                self.assertEqual(delta['text'], 'First ')
                self.assertEqual((delta['chat_id'], delta['agent_id'], delta['job_id']), (cid, aid, jid))
                with self.h.lock:
                    self.assertFalse(self.h.db.execute("SELECT 1 FROM messages WHERE chat_id=? AND role='assistant'", (cid,)).fetchone())
                self.done(jid)
                replies = [m['text'] for m in self.h.history(cid)['messages'] if m['role'] == 'assistant']
                self.assertEqual(replies, ['Final answer'])
                if engine == 'claude':
                    call = json.loads((self.root / 'agents' / aid / 'fake_calls.jsonl').read_text().splitlines()[0])
                    for flag in ('--include-partial-messages', '--verbose', '--safe-mode'):
                        self.assertIn(flag, call['argv'])
                session = self.h.db.execute('SELECT sid FROM sessions WHERE chat_id=?', (cid,)).fetchone()
                self.assertEqual(session[0], engine + '-session')
                remaining = list(events.queue)
                self.assertIn('First draft', [e['text'] for e in remaining if e['kind'] == 'delta'])
                self.assertTrue(any(e['kind'] == 'message' and e.get('job_id') == jid for e in remaining))

    def test_both_engines_error_midstream_never_stores_partial_as_success(self):
        for engine in ('claude', 'codex'):
            with self.subTest(engine=engine):
                _, cid, events = self.prepare(engine, {'stream': ['Unfinished'],
                    'stream_delay': .2, 'is_error': True, 'result': 'fake stream failed'})
                jid = self.send(cid, 'Fail after text')['job_id']
                self.assertEqual(self.partial(events)['text'], 'Unfinished')
                self.done(jid)
                self.assertEqual(self.h.db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()[0], 'error')
                messages = self.h.history(cid)['messages']
                self.assertFalse(any(m['role'] == 'assistant' for m in messages))
                self.assertIn('fake stream failed', messages[-1]['text'])
                self.assertIsNone(self.h.db.execute('SELECT sid FROM sessions WHERE chat_id=?', (cid,)).fetchone())

    def test_both_engines_stop_midstream_never_stores_partial(self):
        for engine in ('claude', 'codex'):
            with self.subTest(engine=engine):
                _, cid, events = self.prepare(engine, {'stream': ['Unfinished', 'hidden'], 'stream_delay': 2})
                jid = self.send(cid, 'Stop after text')['job_id']
                self.assertEqual(self.partial(events)['text'], 'Unfinished')
                self.h.stop_job({'job_id': jid})
                poll(lambda: self.h.db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()[0] == 'stopped')
                self.assertFalse(any(m['role'] == 'assistant' for m in self.h.history(cid)['messages']))
                self.assertNotIn(jid, self.h.job_processes)
                self.assertIsNone(self.h.db.execute('SELECT sid FROM sessions WHERE chat_id=?', (cid,)).fetchone())

    def test_both_engines_process_error_after_partial(self):
        for engine in ('claude', 'codex'):
            with self.subTest(engine=engine):
                _, cid, events = self.prepare(engine, {'stream': ['Partial'],
                    'stream_delay': .1, 'stream_exit': 7, 'stderr': 'connection lost'})
                jid = self.send(cid, 'Fail the process')['job_id']
                self.assertEqual(self.partial(events)['text'], 'Partial')
                self.done(jid)
                messages = self.h.history(cid)['messages']
                self.assertFalse(any(m['role'] == 'assistant' for m in messages))
                self.assertIn('connection lost', messages[-1]['text'])

    def test_claude_message_snapshots_do_not_duplicate_deltas_or_expose_tools(self):
        from hub_stream import collect_output
        events = [
            {'type': 'stream_event', 'event': {'type': 'message_start'}},
            {'type': 'stream_event', 'event': {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'Checking'}}},
            {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Checking'}, {'type': 'tool_use', 'input': {'secret': 'private'}}]}},
            {'type': 'stream_event', 'event': {'type': 'content_block_delta', 'delta': {'type': 'input_json_delta', 'partial_json': 'private'}}},
            {'type': 'stream_event', 'event': {'type': 'message_start'}},
            {'type': 'stream_event', 'event': {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'Answer'}}},
            {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Answer'}]}},
            {'type': 'result', 'result': 'Answer'}]
        proc = subprocess.Popen([sys.executable, '-c',
            'import sys; sys.stdout.write(sys.argv[1])',
            ''.join(json.dumps(e) + '\n' for e in events)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        seen = []
        collect_output(proc, 2, 'claude', seen.append)
        self.assertEqual(seen, ['Checking', '', 'Answer'])

    def test_partial_flag_only_when_help_advertises_it_and_cached(self):
        for help_text, flags in (('old CLI', []), ('--include-partial-messages', ['--include-partial-messages'])):
            with self.subTest(help=help_text):
                self.h._claude_partial_support = {}
                with mock.patch('hub_isolation.run_bounded', return_value=subprocess.CompletedProcess([], 0, help_text, '')) as probe:
                    self.assertEqual(self.h.claude_stream_flags('fake'), flags)
                    self.assertEqual(self.h.claude_stream_flags('fake'), flags)
                    self.assertEqual(probe.call_count, 1)

    def test_create_agent_commits_chat_before_response_without_state_poll(self):
        self.h.enqueue = lambda *args: None
        # Fail if the create/send sequence needs the UI's later state sync.
        with mock.patch.object(self.h, 'sync_chats', return_value=None):
            made = self.h.create_agent({'name': 'First agent', 'role': 'Help.'})
            sent = self.send(made['chat_id'], 'My first question')
        message = self.h.db.execute('SELECT text FROM messages WHERE id=?', (sent['message_id'],)).fetchone()
        self.assertEqual(message[0], 'My first question')
