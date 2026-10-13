"""Pip-provided destinations remain literal metadata through approval cards."""
import json
import unittest
from hub_access import APPROVAL_RULE
from hub_approvals import parse_approval_requests
from tests import test_hub as fixture


def request(destination):
    return '```agent-hub\n' + json.dumps({'action': 'approval_request',
        'summary': 'Send this draft', 'details': 'Exact message\nSecond line',
        'destination': destination}) + '\n```'


class ApprovalDestinationTests(unittest.TestCase):
    setUp = fixture.HubCase.setUp

    def test_destination_is_provided_by_pip_never_inferred_from_platform_example(self):
        destination = 'http://127.0.0.1:4841/inbox / @alex_k'
        mid = self.h.add_message(self.cid, self.aid, 'assistant', request(destination))
        self.h.db.commit()
        card = next(m for m in self.h.history(self.cid)['messages'] if m['id'] == mid)['cards'][0]
        self.assertEqual(card['destination'], destination)
        self.assertEqual(card['details'], 'Exact message\nSecond line')
        self.assertNotIn('Instagram', APPROVAL_RULE)
        self.assertIn('Do not guess', APPROVAL_RULE)
        with self.h.lock:
            self.h.enqueue = lambda aid, jid: None
        sent = self.h.send({'chat_id': self.cid, 'message_id': mid, 'index': 0,
                            'action': 'Approve', 'request_id': 'destination-approval-001'}, card=True)
        job = self.h.db.execute('SELECT prompt FROM jobs WHERE id=?', (sent['job_id'],)).fetchone()
        self.assertIn(destination, job['prompt'])
        self.assertIn('Exact message', job['prompt'])

    def test_invalid_destination_leaves_request_readable(self):
        for invalid in ('', 42, {'site': 'guessed'}, 'x' * 2001):
            original = request(invalid)
            clean, cards = parse_approval_requests(original)
            self.assertEqual(clean, original)
            self.assertEqual(cards, [])
