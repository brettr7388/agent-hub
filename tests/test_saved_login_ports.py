"""Local saved-login ports and legacy vault metadata."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub_cdp import origin_matches
from hub_login import LoginError, LoginStore, login_allows_site, validate_site
from hub_browser import BrowserMixin
from hub import HubError


class MemoryVault(LoginStore):
    def __init__(self):
        super().__init__(platform='darwin', binary='memory-vault')
        self.values = {}

    def _read(self, account): return self.values.get(account)
    def _write(self, account, value): self.values[account] = value
    def _delete_account(self, account): self.values.pop(account, None)


class SavedLoginPortTests(unittest.TestCase):
    def test_save_api_rejects_portless_local_before_any_vault_write(self):
        store = MemoryVault()
        owner = SimpleNamespace(login_store=lambda: store)
        for site in ('localhost', '127.0.0.1', '[::1]', 'app.localhost'):
            body = {'site': site, 'username': 'alice', 'password': 'SECRET-CANARY'}
            with self.subTest(site=site), self.assertRaisesRegex(HubError, 'port'):
                BrowserMixin.saved_login_add(owner, body)
            self.assertNotIn('password', body)
            self.assertEqual(store.values, {})

    def test_final_delete_uses_os_vault_index_delete_command(self):
        for platform in ('darwin', 'linux'):
            store = LoginStore(platform=platform, binary='fake-vault')
            item = {'id': 'only', 'site': 'example.com', 'username': 'alice', 'subdomains': []}
            with mock.patch.object(store, '_index', return_value=[item]), \
                 mock.patch.object(store, '_run', return_value=SimpleNamespace(returncode=0)) as run, \
                 mock.patch.object(store, '_write') as write:
                store.delete('only')
            expected = (['delete-generic-password', '-s', 'Agent Hub', '-a', '__saved_logins__']
                        if platform == 'darwin' else ['clear', 'service', 'Agent Hub', 'account', '__saved_logins__'])
            self.assertEqual(run.call_args_list[-1].args[0], expected)
            self.assertEqual(run.call_count, 2)
            write.assert_not_called()

    def test_new_local_logins_require_explicit_valid_port(self):
        for site in ('localhost:1', 'localhost:65535', '127.0.0.1:4841',
                     '[::1]:4841', 'sub.localhost:4841'):
            with self.subTest(site=site): self.assertEqual(validate_site(site), site)
        for site in ('localhost', '127.0.0.1', '[::1]', 'sub.localhost',
                     '*.localhost:4841', 'localhost:0', 'localhost:65536',
                     '[::1]:0', '[::1]:65536', '[::2]:4841',
                     'sub.localhost:65536', 'sub.localhost:4841/path'):
            with self.subTest(site=site), self.assertRaises(LoginError): validate_site(site)

    def test_local_offers_and_fill_origins_match_exact_host_and_port(self):
        cases = (
            ('localhost:4841', 'http://localhost:4841/inbox', 'localhost:4841'),
            ('127.0.0.1:4841', 'http://127.0.0.1:4841/inbox', '127.0.0.1:4841'),
            ('[::1]:4841', 'http://[::1]:4841/inbox', '[::1]:4841'),
            ('sub.localhost:4841', 'http://sub.localhost:4841/inbox', 'sub.localhost:4841'),
        )
        for site, url, offered in cases:
            login = {'site': site, 'subdomains': []}
            with self.subTest(site=site):
                self.assertTrue(login_allows_site(login, offered))
                self.assertTrue(origin_matches(url, login))
                self.assertFalse(login_allows_site(login, site.rsplit(':', 1)[0] + ':4842'))
                self.assertFalse(origin_matches(url.replace(':4841/', ':4842/'), login))
                self.assertFalse(origin_matches('http://else.localhost:4841/inbox', login))
                self.assertFalse(origin_matches(url.replace('http://', 'http://@'), login))
        self.assertFalse(origin_matches('http://else.[::1]:4841/inbox',
                                        {'site': '[::1]:4841', 'subdomains': []}))

    def test_legacy_portless_entry_remains_visible_but_unusable(self):
        for site, url, offered in (
            ('localhost', 'http://localhost:4841/inbox', 'localhost:4841'),
            ('127.0.0.1', 'http://127.0.0.1:4841/inbox', '127.0.0.1:4841'),
            ('[::1]', 'http://[::1]:4841/inbox', '[::1]:4841'),
            ('sub.localhost', 'http://sub.localhost:4841/inbox', 'sub.localhost:4841'),
        ):
            with self.subTest(site=site):
                store = MemoryVault()
                item = {'id': 'legacy', 'site': site, 'username': 'alice', 'subdomains': []}
                store.values[store.INDEX] = json.dumps([item])
                store.values[site + ':alice'] = 'SECRET-CANARY'
                listed = store.list()
                self.assertEqual(listed[0]['site'], site)
                self.assertTrue(listed[0]['needs_port'])
                self.assertNotIn('SECRET-CANARY', json.dumps(listed))
                self.assertFalse(login_allows_site(item, offered))
                self.assertFalse(origin_matches(url, item))
                with self.assertRaisesRegex(LoginError, 'port'): store.get('legacy')
                store.delete('legacy')
                self.assertEqual(store.values, {})

    def test_last_delete_removes_index_and_other_entries_keep_it(self):
        store = MemoryVault()
        first = store.add('example.com', 'alice', 'FIRST')
        second = store.add('localhost:4841', 'bob', 'SECOND')
        self.assertFalse(store.list()[0]['needs_port'])
        self.assertFalse(store.list()[1]['needs_port'])
        store.delete(first['id'])
        self.assertIn(store.INDEX, store.values)
        self.assertEqual(store.get(second['id'])['password'], 'SECOND')
        store.delete(second['id'])
        self.assertEqual(store.values, {})

    def test_nonlocal_https_default_port_behavior(self):
        login = {'site': 'example.com', 'subdomains': ['accounts.example.com']}
        self.assertTrue(origin_matches('https://example.com/login', login))
        self.assertTrue(origin_matches('https://accounts.example.com:443/login', login))
        self.assertFalse(origin_matches('https://example.com:444/login', login))
        self.assertFalse(origin_matches('http://example.com/login', login))

    def test_explicit_local_default_port_matches_browser_canonical_origin(self):
        for host in ('localhost', '127.0.0.1', '[::1]', 'app.localhost'):
            with self.subTest(host=host):
                self.assertTrue(origin_matches('http://' + host + '/login', {'site': host + ':80'}))
                self.assertTrue(origin_matches('https://' + host + '/login', {'site': host + ':443'}))
                self.assertFalse(origin_matches('http://' + host + '/login', {'site': host + ':443'}))
                self.assertFalse(origin_matches('https://' + host + '/login', {'site': host + ':80'}))
                self.assertFalse(origin_matches('http://' + host + '/login', {'site': host}))


if __name__ == '__main__': unittest.main()
