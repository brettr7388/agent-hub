"""Stopped-turn notices use observed CLI tool events, not prompt wording."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

import hub_stop_notice
from hub_stream import collect_output
import test_hub
from test_hub import poll


class StopNoticeIntegration(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    send = test_hub.HubCase.send

    def _stop_after_delta(self, events, prompt):
        agent_folder = self.root / 'agents' / self.aid
        (agent_folder / 'fake_responses.json').write_text(json.dumps([{
            'events': events, 'stream': ['Partial answer', 'more'], 'stream_delay': 10}]))
        import queue
        updates = queue.Queue()
        with self.h.lock:
            self.h.subscribers.add(updates)
        self.addCleanup(self.h.subscribers.discard, updates)
        jid = self.send(self.cid, prompt)['job_id']
        poll(lambda: any(e['kind'] == 'delta' and e.get('job_id') == jid for e in list(updates.queue)))
        self.h.stop_job({'job_id': jid})
        poll(lambda: self.h.db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()[0] == 'stopped')
        poll(lambda: jid not in self.h._tool_activity)
        messages = self.h.history(self.cid)['messages']
        self.assertFalse(any(m['role'] == 'assistant' for m in messages))
        self.assertEqual(len((agent_folder / 'fake_calls.jsonl').read_text().splitlines()), 1)
        self.assertNotIn(jid, self.h._tool_activity)
        return messages[-1]['text']

    def test_plain_answer_stopped_without_side_effect_warning(self):
        notice = self._stop_after_delta([], 'Please answer in plain text; no tools.')
        self.assertEqual(notice, 'Turn stopped. No automatic replay.')

    def test_tool_event_keeps_side_effect_warning(self):
        event = {'type': 'stream_event', 'event': {'type': 'content_block_start',
                 'content_block': {'type': 'tool_use', 'name': 'Write'}}}
        notice = self._stop_after_delta([event], 'Please answer.')
        self.assertIn('verify any side effects', notice)
        self.assertIn('No automatic replay', notice)


class ToolEventObserver(unittest.TestCase):
    def test_exact_events_and_prose(self):
        claude_start = {'type': 'stream_event', 'event': {'type': 'content_block_start',
                        'content_block': {'type': 'tool_use'}}}
        claude_assistant = {'type': 'assistant', 'message': {'content': [{'type': 'tool_use'}]}}
        self.assertTrue(hub_stop_notice.action_observed('claude', claude_start))
        self.assertTrue(hub_stop_notice.action_observed('claude', claude_assistant))
        for item_type in ('command_execution', 'mcp_tool_call', 'file_change'):
            for status in ('item.started', 'item.completed'):
                self.assertTrue(hub_stop_notice.action_observed('codex',
                    {'type': status, 'item': {'type': item_type}}))
        for engine, event in (
                ('claude', {'type': 'stream_event', 'event': {'type': 'content_block_delta',
                            'delta': {'type': 'text_delta', 'text': 'I used a tool'}}}),
                ('codex', {'type': 'item.updated', 'item': {'type': 'agent_message',
                           'text': 'I changed a file'}}),
                ('codex', {'type': 'item.completed', 'item': {'type': 'agent_message',
                           'text': 'Ran a command'}})):
            self.assertFalse(hub_stop_notice.action_observed(engine, event))

    def test_stream_observer_sees_tool_event_without_forwarding_tool_text(self):
        events = [{'type': 'item.started', 'item': {'type': 'command_execution', 'command': 'secret'}},
                  {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Answer'}}]
        proc = subprocess.Popen([sys.executable, '-c',
            'import sys; sys.stdout.write(sys.argv[1])',
            ''.join(json.dumps(event) + '\n' for event in events)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        observed, text = [], []
        collect_output(proc, 2, 'codex', text.append, observed.append)
        self.assertEqual(text, ['Answer'])
        self.assertEqual(observed, events)
