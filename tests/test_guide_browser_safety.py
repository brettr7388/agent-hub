"""Browser proposal instructions are visible before creation and durable."""
import unittest

import test_hub
from hub_guide import BROWSER_SAFETY, proposal


class GuideBrowserSafety(unittest.TestCase):
    setUp = test_hub.HubCase.setUp

    def test_browser_proposal_has_account_and_send_rules_before_create(self):
        card = proposal(self.h, {'action': 'create_agent', 'name': 'Browser helper',
                                'instructions': 'Research products.', 'chrome': True})
        self.assertIn(BROWSER_SAFETY, card['instructions'])
        self.assertEqual(proposal(self.h, card)['instructions'], card['instructions'])
        made = self.h.create_agent({**card, 'role': card['instructions']})
        self.assertIn(BROWSER_SAFETY, self.h.agents()[made['agent']['id']]['instructions'])

    def test_browser_rules_apply_to_nested_group_proposals(self):
        group = proposal(self.h, {'action': 'create_group', 'name': 'Research crew',
                                 'agents': ['Assistant', {'action': 'create_agent', 'name': 'Browser helper',
                                             'instructions': 'Research products.', 'chrome': True}]})
        self.assertIn(BROWSER_SAFETY, group['agents'][1]['instructions'])

    def test_plain_proposal_keeps_instructions(self):
        card = proposal(self.h, {'action': 'create_agent', 'name': 'Plain helper',
                                'instructions': 'Research products.', 'chrome': False})
        self.assertEqual(card['instructions'], 'Research products.')
