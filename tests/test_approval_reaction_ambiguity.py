"""Message reactions only act when exactly one actionable card remains."""
import json
import unittest

import test_hub
from hub_approvals import ApprovalMixin


def approval(title):
    return '```agent-hub\n' + json.dumps({'action': 'approval_request',
        'summary': title, 'details': 'Reviewed details.'}) + '\n```'


class ApprovalReactionAmbiguity(unittest.TestCase):
    setUp = test_hub.HubCase.setUp

    def test_approval_helper_never_selects_first_of_multiple_targets(self):
        card = {'kind': 'approval_request', 'title': 'Draft', 'actions': ['Approve', "Don't"]}
        for cards in ([card, card], [card, {'kind': 'proposal', 'status': 'pending'}],
                      [card, {'title': 'Other', 'actions': ['Approve', 'Skip']}]):
            for emoji in ('👍', '✅', '👎'):
                self.assertIsNone(ApprovalMixin.approval_reaction(cards, emoji))

    def test_multiple_approval_cards_leave_reaction_nonactionable(self):
        mid = self.h.add_message(self.cid, self.aid, 'assistant',
                                 approval('First') + '\n' + approval('Second'))
        self.h.db.commit()

        result = self.h.react({'message_id': mid, 'emoji': '👍',
                               'confirm': True, 'request_id': 'ambiguous-approvals-001'})

        self.assertIsNone(result['job_id'])
        self.assertNotIn('confirmation_required', result)
        self.assertIn('hint', result)
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM decisions WHERE message_id=?',
                                           (mid,)).fetchone()[0], 0)
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM jobs WHERE reply_to=?',
                                           (mid,)).fetchone()[0], 0)

    def test_multiple_pending_guide_proposals_never_create_from_reactions(self):
        specs = [{'action': 'create_agent', 'name': name, 'instructions': 'Write clearly.'}
                 for name in ('FirstWriter', 'SecondWriter')]
        text = '\n'.join('```agent-hub\n' + json.dumps(spec) + '\n```' for spec in specs)
        before = set(self.h.agents())
        for emoji in ('👍', '✅', '👎'):
            for confirmed in (False, True):
                with self.subTest(emoji=emoji, confirmed=confirmed):
                    mid = self.h.add_message(self.h.guide_chat(), self.h.guide_id(), 'assistant', text)
                    self.h.db.commit()
                    result = self.h.react({'message_id': mid, 'emoji': emoji, 'active': True,
                                           'confirm': confirmed, 'request_id': 'guide-ambiguity-' + str(mid)})
                    self.assertIsNone(result['job_id'])
                    self.assertNotIn('confirmation_required', result)
                    self.assertEqual(set(self.h.agents()), before)
                    stored = json.loads(self.h.db.execute('SELECT cards FROM messages WHERE id=?', (mid,)).fetchone()[0])
                    self.assertEqual([card['status'] for card in stored], ['pending', 'pending'])

    def test_resolved_card_cannot_dispatch_a_prose_approval(self):
        mid = self.h.add_message(self.cid, self.aid, 'assistant', approval('Send draft'))
        self.h.db.execute('INSERT INTO decisions(message_id,card_index,action) VALUES(?,?,?)',
                          (mid, 0, "Don't"))
        self.h.db.commit()
        result = self.h.react({'message_id': mid, 'emoji': '✅', 'active': True,
                               'confirm': True, 'request_id': 'resolved-reaction-001'})
        self.assertIsNone(result['job_id'])
        self.assertNotIn('confirmation_required', result)
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM jobs WHERE reply_to=?', (mid,)).fetchone()[0], 0)

    def test_single_action_card_after_display_only_card_is_targeted(self):
        mid = self.h.add_message(self.cid, self.aid, 'assistant', 'A status update.')
        cards = [
            {'kind': 'display', 'title': 'Status'},
            {'title': 'Continue', 'text': 'Proceed?', 'actions': ['Continue', 'Skip']},
        ]
        self.h.db.execute('UPDATE messages SET cards=? WHERE id=?', (json.dumps(cards), mid))
        self.h.db.commit()

        result = self.h.react({'message_id': mid, 'emoji': '👍',
                               'request_id': 'after-display-preview-01'})

        self.assertTrue(result['confirmation_required'])
        self.assertEqual(result['index'], 1)
        self.assertEqual(result['action'], 'Continue')

    def test_decided_guide_proposal_does_not_mask_remaining_proposal(self):
        specs = [
            {'action': 'create_agent', 'name': 'FirstWriter', 'instructions': 'Write clearly.'},
            {'action': 'create_agent', 'name': 'SecondWriter', 'instructions': 'Write clearly.'},
        ]
        text = '\n'.join('```agent-hub\n' + json.dumps(spec) + '\n```' for spec in specs)
        mid = self.h.add_message(self.h.guide_chat(), self.h.guide_id(), 'assistant', text)
        self.h.db.commit()
        self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'dismiss'})

        result = self.h.react({'message_id': mid, 'emoji': '✅',
                               'request_id': 'remaining-guide-preview-01'})

        self.assertTrue(result['confirmation_required'])
        self.assertTrue(result['guide_proposal'])
        self.assertEqual(result['index'], 1)

    def test_approval_and_guide_proposal_together_are_ambiguous(self):
        proposals = [
            {'action': 'create_agent', 'name': 'FirstWriter', 'instructions': 'Write clearly.'},
            {'action': 'create_agent', 'name': 'SecondWriter', 'instructions': 'Write clearly.'},
        ]
        text = approval('Approve draft') + '\n' + '\n'.join(
            '```agent-hub\n' + json.dumps(proposal) + '\n```' for proposal in proposals)
        mid = self.h.add_message(self.h.guide_chat(), self.h.guide_id(), 'assistant', text)
        self.h.db.commit()
        self.h.guide_proposal({'message_id': mid, 'index': 1, 'action': 'dismiss'})

        result = self.h.react({'message_id': mid, 'emoji': '👎',
                               'request_id': 'mixed-targets-preview-01'})

        self.assertIsNone(result['job_id'])
        self.assertNotIn('confirmation_required', result)
        stored = json.loads(self.h.db.execute('SELECT cards FROM messages WHERE id=?', (mid,)).fetchone()[0])
        self.assertEqual(stored[1]['status'], 'dismissed')
        self.assertEqual(stored[2]['status'], 'pending')
