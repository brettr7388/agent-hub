"""Destination metadata is literal and never inferred from prose."""
import json
import unittest

from hub_approvals import parse_approval_requests


class ApprovalDestinationTests(unittest.TestCase):
    def test_explicit_destination_preserves_exact_pip_text(self):
        destination = '  127.0.0.1:4841 / @testuser <b>local</b>  '
        raw = {'action': 'approval_request', 'summary': 'Send draft', 'details': 'Exact text', 'destination': destination}
        clean, cards = parse_approval_requests('```agent-hub\n' + json.dumps(raw) + '\n```')
        self.assertEqual(clean, '')
        self.assertEqual(cards[0]['destination'], destination)

    def test_missing_destination_is_not_inferred_from_summary_or_details(self):
        raw = {'action': 'approval_request', 'summary': 'Send on Instagram', 'details': 'Exact text for @testuser'}
        _, cards = parse_approval_requests('```agent-hub\n' + json.dumps(raw) + '\n```')
        self.assertNotIn('destination', cards[0])


if __name__ == '__main__': unittest.main()
