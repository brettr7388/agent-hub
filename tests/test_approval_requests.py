"""Approval request cards and decisions, using only the local fake CLI."""
import json
import unittest

import hub
from hub_approvals import ApprovalMixin, parse_approval_requests
from tests import test_hub as fixture


def fence(**fields):
    return '```agent-hub\n' + json.dumps(fields) + '\n```'


class ApprovalParserTests(unittest.TestCase):
    setUp = fixture.HubCase.setUp
    def test_only_complete_top_level_approval_objects_become_cards(self):
        valid = fence(action='approval_request', summary='Send the reviewed draft',
                      details='Recipient: Alex. Text: Hello.')
        guide = fence(action='create_agent', name='Writer', instructions='Write clearly.')
        invalid = fence(action='approval_request', summary=' ', details='Something')
        malformed = '```agent-hub\n{bad JSON\n```'
        quoted = '> ' + valid.replace('\n', '\n> ')
        nested = '```markdown\n' + valid + '\n```'
        original = '\n'.join(('Before', valid, guide, invalid, malformed, quoted, nested, 'After'))
        clean, cards = parse_approval_requests(original)
        self.assertEqual(cards, [{'kind': 'approval_request', 'title': 'Send the reviewed draft',
                                  'text': 'Recipient: Alex. Text: Hello.',
                                  'summary': 'Send the reviewed draft',
                                  'details': 'Recipient: Alex. Text: Hello.',
                                  'actions': ['Approve', "Don't"]}])
        self.assertEqual(clean, original.replace(valid + '\n', '', 1))

    def test_preserves_approval_string_whitespace_exactly(self):
        clean, cards = parse_approval_requests(fence(action='approval_request',
            summary=' Send this draft ', details='Line one\n\nLine two  '))
        self.assertEqual(clean, '')
        self.assertEqual(cards[0]['summary'], ' Send this draft ')
        self.assertEqual(cards[0]['details'], 'Line one\n\nLine two  ')
        self.assertEqual(cards[0]['title'], cards[0]['summary'])
        self.assertEqual(cards[0]['text'], cards[0]['details'])

    def test_malformed_fences_cannot_create_legacy_card_controls(self):
        legacy = 'CARD: ' + json.dumps({'title': 'Send', 'text': 'hello', 'actions': ['Approve', 'Skip']})
        for text in ('```agent-hub\n{bad JSON\n' + legacy + '\n```',
                     '```markdown\n' + legacy + '\n```'):
            mid = self.h.add_message(self.cid, self.aid, 'assistant', text)
            self.h.db.commit()
            saved = next(m for m in self.h.history(self.cid)['messages'] if m['id'] == mid)
            self.assertEqual(saved['text'], text)
            self.assertEqual(saved['cards'], [])

    def test_multiple_cards_and_non_assistant_messages(self):
        first = fence(action='approval_request', summary='First', details='One')
        second = fence(action='approval_request', summary='Second', details='Two')
        with self.h.lock:
            user_id = self.h.add_message(self.cid, self.aid, 'user', first)
            assistant_id = self.h.add_message(self.cid, self.aid, 'assistant', first + '\n' + second)
            self.h.db.commit()
        rows = {m['id']: m for m in self.h.history(self.cid)['messages']}
        self.assertEqual(rows[user_id]['text'], first)
        self.assertEqual(rows[user_id]['cards'], [])
        self.assertEqual([c['title'] for c in rows[assistant_id]['cards']], ['First', 'Second'])
        self.assertNotIn('agent-hub', rows[assistant_id]['text'])

    def test_malformed_approval_from_guide_stays_visible(self):
        for invalid in (fence(action='approval_request', summary='', details='Needs a summary.'),
                        '```agent-hub\n{bad JSON\n```'):
            with self.h.lock:
                mid = self.h.add_message(self.h.guide_chat(), self.h.guide_id(), 'assistant', invalid)
                self.h.db.commit()
            saved = next(m for m in self.h.history(self.h.guide_chat())['messages'] if m['id'] == mid)
            self.assertEqual(saved['text'], invalid)
            self.assertEqual(saved['cards'], [])

    def test_response_wording_is_exact(self):
        card = {'kind': 'approval_request', 'title': 'Send the reviewed draft',
                'summary': 'Send the reviewed draft'}
        self.assertEqual(ApprovalMixin.approval_response(card, 'Approve'),
                         'Yes, approved: Send the reviewed draft — exactly as shown.')
        self.assertEqual(ApprovalMixin.approval_response(card, "Don't"), "No, don't do that.")
        self.assertEqual(ApprovalMixin.approval_reaction([card], '✅'), (0, 'Approve'))
        self.assertEqual(ApprovalMixin.approval_reaction([card], '👎'), (0, "Don't"))

    def test_button_decision_targets_original_pip_in_group_once(self):
        self.h.create_agent({'name': 'Analyst', 'role': 'Analyze.', 'model': 'haiku'})
        cid = self.h.group({'name': 'Team', 'agents': ['assistant', 'analyst']})['chat']['id']
        with self.h.lock:
            mid = self.h.add_message(cid, 'analyst', 'assistant',
                fence(action='approval_request', summary='Send the reviewed draft', details='To Alex.'))
            self.h.db.commit()
        payload = {'chat_id': cid, 'request_id': 'approval-button-001', 'message_id': mid,
                   'index': 0, 'action': 'Approve'}
        accepted = self.h.send(payload, card=True)
        self.assertTrue(self.h.send(payload, card=True)['duplicate'])
        with self.assertRaises(hub.HubError) as error:
            self.h.send(dict(payload, request_id='approval-button-002'), card=True)
        self.assertEqual(error.exception.status, 409)
        user = self.h.db.execute('SELECT * FROM messages WHERE id=?', (accepted['message_id'],)).fetchone()
        self.assertEqual(user['text'], 'Yes, approved: Send the reviewed draft — exactly as shown.')
        self.assertEqual(user['reply_to'], mid)
        job = self.h.db.execute('SELECT agent_id FROM jobs WHERE id=?', (accepted['job_id'],)).fetchone()
        self.assertEqual(job['agent_id'], 'analyst')
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM decisions WHERE message_id=?', (mid,)).fetchone()[0], 1)

    def test_reaction_approval_uses_same_decision_and_confirmation(self):
        with self.h.lock:
            mid = self.h.add_message(self.cid, self.aid, 'assistant',
                fence(action='approval_request', summary='Publish this draft', details='Text follows.'))
            self.h.db.commit()
        preview = self.h.react({'message_id': mid, 'emoji': '👍', 'request_id': 'reaction-preview-01'})
        self.assertTrue(preview['confirmation_required'])
        self.assertFalse(self.h.db.execute('SELECT 1 FROM decisions WHERE message_id=?', (mid,)).fetchone())
        result = self.h.react({'message_id': mid, 'emoji': '✅', 'confirm': True,
                               'request_id': 'reaction-confirm-01'})
        self.assertIsNotNone(result['job_id'])
        self.assertEqual(self.h.react({'message_id': mid, 'emoji': '✅', 'confirm': True,
                                       'request_id': 'reaction-confirm-01'})['job_id'], result['job_id'])
        decision = self.h.db.execute('SELECT action FROM decisions WHERE message_id=?', (mid,)).fetchone()
        self.assertEqual(decision['action'], 'Approve')
        replies = self.h.db.execute('SELECT text FROM messages WHERE reply_to=? AND role=?', (mid, 'user')).fetchall()
        self.assertEqual([row['text'] for row in replies], ['Yes, approved: Publish this draft — exactly as shown.'])
