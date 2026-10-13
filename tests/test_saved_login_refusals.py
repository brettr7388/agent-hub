"""Saved-login fill refusals name the checked tab without leaking secrets."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub_cdp import fill_login


class EmptyFormCDP:
    def __init__(self, url):
        self.url = url
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params))
        if method == 'Page.getFrameTree':
            return {'frameTree': {'frame': {'id': 'top', 'url': self.url}}}
        if method == 'DOM.getDocument': return {'root': {'nodeId': 1}}
        if method == 'DOM.querySelectorAll': return {'nodeIds': []}
        raise AssertionError('No secret should be released when the form is absent')


class SavedLoginRefusalTests(unittest.TestCase):
    def test_missing_form_names_tab_without_query_fragment_or_fields(self):
        client = EmptyFormCDP('http://127.0.0.1:4841/inbox?token=QUERY-CANARY#FRAGMENT-CANARY')
        login = {'site': '127.0.0.1:4841', 'username': 'USERNAME-CANARY',
                 'password': 'PASSWORD-CANARY', 'subdomains': []}
        refusal = fill_login(client, login)
        self.assertIn("Pip's login tab (127.0.0.1:4841)", refusal)
        self.assertIn('refused', refusal)
        for canary in ('QUERY-CANARY', 'FRAGMENT-CANARY', 'USERNAME-CANARY', 'PASSWORD-CANARY'):
            self.assertNotIn(canary, refusal)
        self.assertFalse(any(method == 'Runtime.callFunctionOn' for method, _ in client.calls))

    def test_ipv6_refusal_keeps_brackets_and_port(self):
        client = EmptyFormCDP('http://[::1]:4841/login?token=hidden')
        refusal = fill_login(client, {'site': '[::1]:4841', 'username': 'a',
                                      'password': 'b', 'subdomains': []})
        self.assertIn('[::1]:4841)', refusal)
        self.assertNotIn('/login', refusal)
        self.assertNotIn('hidden', refusal)

    def test_changed_page_refusal_names_checked_location_without_url_secrets(self):
        client = EmptyFormCDP('http://127.0.0.1:4841/inbox?token=URL-CANARY#hidden')
        refusal = fill_login(client, {'site': '127.0.0.1:4841', 'username': 'USER-CANARY',
                                      'password': 'PASSWORD-CANARY', 'subdomains': []},
                             expected_url='http://127.0.0.1:4841/login')
        self.assertIn('127.0.0.1:4841)', refusal)
        self.assertNotIn('/inbox', refusal)
        for canary in ('URL-CANARY', 'hidden', 'USER-CANARY', 'PASSWORD-CANARY'):
            self.assertNotIn(canary, refusal)


if __name__ == '__main__': unittest.main()
