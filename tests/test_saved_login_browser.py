"""Local account authority stays pinned through browser selection and fill."""
from pathlib import Path
import unittest

from hub_browser import PipBrowser
from test_browser_access import FakeBroker, page


class SavedLoginBrowserTests(unittest.TestCase):
    def browser(self, pages=()):
        browser = PipBrowser(Path('/unused'))
        browser.broker = FakeBroker(pages)
        browser.ensure = lambda: (None, browser.broker.socket_path)
        browser._front = lambda: None
        browser._binary = lambda: '/fake/chrome'
        return browser

    def test_all_local_authorities_open_on_http_and_reuse_exact_port(self):
        for site in ('localhost:4841', '127.0.0.1:4841', '[::1]:4841', 'app.localhost:4841'):
            with self.subTest(site=site):
                browser = self.browser([page('other-port', 'http://' + site.replace('4841', '4842'))])
                browser.open(site, requester='writer')
                browser.open(site, requester='writer')
                self.assertEqual(browser.broker.pages[-1]['url'], 'http://' + site)
                self.assertEqual(sum(method == 'Target.createTarget' for method, _ in browser.broker.calls), 1)

    def test_requested_authority_cannot_override_saved_login_port(self):
        for saved in ('127.0.0.1', '127.0.0.1:4842'):
            browser = self.browser([page('login', 'http://127.0.0.1:4841/inbox')])
            login = {'site': saved, 'username': 'testuser', 'password': 'CANARY', 'subdomains': []}
            result = browser.fill(login, requester='writer', site='127.0.0.1:4841')
            self.assertIn('refused', result)
            self.assertNotIn('CANARY', result)
            self.assertEqual(browser.broker.sessions, [])


if __name__ == '__main__': unittest.main()
