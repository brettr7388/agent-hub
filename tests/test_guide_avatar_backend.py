"""Guide proposal avatars are stable between review and creation."""
import json
import unittest

import test_hub


class GuideProposalAvatars(unittest.TestCase):
    setUp = test_hub.HubCase.setUp

    def pending(self, spec):
        mid = self.h.add_message('agent:guide', 'guide', 'assistant',
            '```agent-hub\n' + json.dumps(spec) + '\n```')
        self.h.db.commit()
        cards = json.loads(self.h.db.execute('SELECT cards FROM messages WHERE id=?', (mid,)).fetchone()[0])
        return mid, cards[0]['proposal']

    def test_generated_style_matches_created_agent(self):
        spec = {'action': 'create_agent', 'name': 'Proposal Writer', 'title': 'Writes clear copy',
                'instructions': 'Write and edit concise drafts.'}
        mid, pending = self.pending(spec)
        self.assertIsNotNone(pending['pip_style'])
        result = self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'create'})
        self.assertEqual(result['result']['agent']['pip_style'], pending['pip_style'])

    def test_explicit_style_survives_normalization_and_creation(self):
        style = {'palette': 'coral', 'accessory': 'pencil', 'eyes': 'happy',
                 'antenna': 'star', 'visor': 'round'}
        mid, pending = self.pending({'action': 'create_agent', 'name': 'Explicit Writer',
            'instructions': 'Write copy.', 'pip_style': style})
        self.assertEqual(pending['pip_style'], style)
        result = self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'create'})
        self.assertEqual(result['result']['agent']['pip_style'], style)

    def test_emoji_avatar_still_has_matching_persisted_pip_style(self):
        mid, pending = self.pending({'action': 'create_agent', 'name': 'Emoji Writer',
            'instructions': 'Write copy.', 'avatar_style': 'emoji'})
        self.assertEqual(pending['avatar_style'], 'emoji')
        result = self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'create'})
        self.assertEqual(result['result']['agent']['avatar_style'], 'emoji')
        self.assertEqual(result['result']['agent']['pip_style'], pending['pip_style'])

    def test_group_child_proposal_keeps_its_generated_style(self):
        mid, pending = self.pending({'action': 'create_group', 'name': 'Writing Team', 'agents': [
            {'action': 'create_agent', 'name': 'Group Writer', 'instructions': 'Write copy.'},
            'Assistant']})
        child = pending['agents'][0]
        result = self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'create'})
        created = result['result']['chat']['agents']
        agent_id = next(aid for aid in created if aid == 'group-writer')
        self.assertEqual(self.h.agents()[agent_id]['pip_style'], child['pip_style'])


if __name__ == '__main__':
    unittest.main()
