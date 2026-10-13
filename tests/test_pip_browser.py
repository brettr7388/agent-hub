"""Pip browser security checks with fake vault and CDP; no real browser or keychain."""
import json
import io
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub_browser import CDPError, PipBrowser, parse_browser_cards
from hub_cdp import fill_login
from hub_login import LoginStore, validate_site, validate_subdomains
import hub
import hub_export
import test_hub


class BrowserCardParsingTests(unittest.TestCase):
    @staticmethod
    def fence(payload):
        return '```agent-hub\n' + json.dumps(payload) + '\n```'

    def test_signin_and_login_requests_are_extracted(self):
        for payload in (
            {'action': 'signin_request', 'site': 'example.com', 'reason': 'Review the page'},
            {'action': 'login_fill_request', 'site': 'example.com', 'reason': 'Use saved login'},
        ):
            with self.subTest(payload=payload):
                clean, cards = parse_browser_cards('Before\n' + self.fence(payload) + '\nAfter')
                self.assertEqual(clean, 'Before\nAfter')
                self.assertEqual(len(cards), 1)
                self.assertEqual(cards[0]['site'], payload['site'])
                self.assertEqual(cards[0]['kind'], payload['action'])
                self.assertNotIn('password', json.dumps(cards).lower())

    def test_invalid_or_secret_bearing_blocks_remain_plain_text(self):
        bad = [
            {'action': 'signin_request', 'site': 'example.com', 'reason': 'x', 'password': 'CANARY-SECRET'},
            {'action': 'login_fill_request', 'site': 'example.com', 'reason': 'x', 'username': 'alice'},
            {'action': 'signin_request', 'site': 'https://example.com/login', 'reason': 'x'},
            {'action': 'signin_request', 'site': 'example.com', 'reason': ''},
            {'action': 'signin_request', 'site': 'example.com', 'reason': 'x', 'extra': 'x'},
            {'action': 'unknown', 'site': 'example.com', 'reason': 'x'},
            ['signin_request', 'example.com'],
        ]
        for payload in bad:
            with self.subTest(payload=payload):
                source = self.fence(payload)
                clean, cards = parse_browser_cards(source)
                self.assertEqual(cards, [])
                self.assertEqual(clean, source)
        for source in ('```agent-hub\n{broken\n```',
                       'Here is a quote: ' + self.fence({'action': 'signin_request', 'site': 'example.com', 'reason': 'x'}),
                       '```json\n{"action":"signin_request","site":"example.com","reason":"x"}\n```'):
            with self.subTest(source=source):
                clean, cards = parse_browser_cards(source)
                self.assertEqual(cards, [])
                self.assertEqual(clean, source)


class DomainValidationTests(unittest.TestCase):
    def test_registrable_domain_only(self):
        self.assertEqual(validate_site('example.com'), 'example.com')
        self.assertEqual(validate_site('example.co.uk'), 'example.co.uk')
        self.assertEqual(validate_site('localhost:4841'), 'localhost:4841')
        self.assertEqual(validate_site('127.0.0.1:4841'), '127.0.0.1:4841')
        for value in ('', 'example', 'com', 'co.uk', 'sub.example.com', 'https://example.com',
                      'example.com/path', 'example.com:443', 'example.com.evil',
                      'evil@example.com', '*.example.com', 'example.com.',
                      'localhost.evil.com', '127.0.0.2', 'example..com', 'localhost', '127.0.0.1'):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                validate_site(value)

    def test_subdomains_are_within_site(self):
        accepted = validate_subdomains('example.com', ['accounts.example.com', 'www.example.com'])
        self.assertEqual(set(accepted), {'accounts.example.com', 'www.example.com'})
        for values in (['example.com.evil'], ['evil.com'], ['*.example.com'],
                       ['https://accounts.example.com'], ['accounts.example.com/path']):
            with self.subTest(values=values), self.assertRaises((ValueError, TypeError)):
                validate_subdomains('example.com', values)


FAKE_SECURITY = r'''#!{python}
import json, os, pathlib, shlex, sys
args = sys.argv[1:]
vault = pathlib.Path(os.environ['FAKE_SECURITY_VAULT'])
log = pathlib.Path(os.environ['FAKE_SECURITY_LOG'])
with log.open('a') as f: f.write(json.dumps(args) + '\n')
items = json.loads(vault.read_text()) if vault.exists() else {{}}
if args == ['-i']:
    lines = sys.stdin.read().splitlines()
    for line in lines:
        parts = shlex.split(line)
        if not parts: continue
        if parts[0] != 'add-generic-password': sys.exit(2)
        service = parts[parts.index('-s')+1]
        account = parts[parts.index('-a')+1]
        items[service + '\\0' + account] = bytes.fromhex(parts[parts.index('-X')+1]).decode()
    vault.write_text(json.dumps(items))
    sys.exit(0)
if not args: sys.exit(2)
op = args[0]
service = args[args.index('-s')+1]
account = args[args.index('-a')+1]
key = service + '\\0' + account
if op == 'find-generic-password':
    if key not in items: sys.exit(44)
    if '-w' in args: print(items[key])
    else: print('password: ' + items[key])
elif op == 'delete-generic-password':
    if key not in items: sys.exit(44)
    del items[key]
    vault.write_text(json.dumps(items))
else: sys.exit(2)
'''

FAKE_SECRET_TOOL = r'''#!{python}
import json, os, pathlib, sys
args = sys.argv[1:]
vault = pathlib.Path(os.environ['FAKE_SECURITY_VAULT'])
log = pathlib.Path(os.environ['FAKE_SECURITY_LOG'])
with log.open('a') as f: f.write(json.dumps(args) + '\n')
items = json.loads(vault.read_text()) if vault.exists() else {{}}
if not args: sys.exit(2)
op = args[0]
key = args[args.index('account')+1]
if op == 'store':
    items[key] = sys.stdin.read()
    vault.write_text(json.dumps(items))
elif op == 'lookup':
    if key not in items: sys.exit(1)
    print(items[key])
elif op == 'clear':
    if key not in items: sys.exit(1)
    del items[key]
    vault.write_text(json.dumps(items))
else: sys.exit(2)
'''


class FakeKeychainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='hub-browser-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.binary = self.root / 'security'
        self.binary.write_text(FAKE_SECURITY.format(python=sys.executable))
        self.binary.chmod(0o700)
        self.vault = self.root / 'fake-vault.json'
        self.log = self.root / 'fake-argv.jsonl'
        env = {'FAKE_SECURITY_VAULT': str(self.vault), 'FAKE_SECURITY_LOG': str(self.log)}
        from unittest import mock
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)

    def test_password_is_only_in_fake_vault_and_never_argv_or_metadata(self):
        secret = 'CANARY-PIP-PASSWORD-92b4'
        store = LoginStore(platform='darwin', binary=str(self.binary))
        self.assertTrue(store.available)
        added = store.add('example.com', 'alice@example.com', secret, ['accounts.example.com'])
        entries = store.list()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['site'], 'example.com')
        self.assertEqual(entries[0]['username'], 'alice@example.com')
        self.assertEqual(entries[0]['subdomains'], ['accounts.example.com'])
        login_id = added['id'] if isinstance(added, dict) else entries[0]['id']
        self.assertEqual(login_id, entries[0]['id'])
        self.assertNotIn(secret, json.dumps(entries))
        self.assertEqual(store.get(login_id)['password'], secret)
        self.assertIn(secret, self.vault.read_text())
        self.assertNotIn(secret, self.log.read_text())
        self.assertNotIn(secret.encode().hex(), self.log.read_text())
        store.delete(login_id)
        self.assertEqual(store.list(), [])
        self.assertNotIn(secret, self.vault.read_text())
        self.assertNotIn('__saved_logins__', self.vault.read_text())

    def test_password_with_shell_metacharacters_round_trips_through_stdin(self):
        secret = 'line one\n"quoted" $HOME `whoami` \\ end'
        store = LoginStore(platform='darwin', binary=str(self.binary))
        item = store.add('example.com', 'alice@example.com', secret)
        self.assertEqual(store.get(item['id'])['password'], secret)
        for argv in self.log.read_text().splitlines():
            self.assertNotIn(secret, argv)
            self.assertNotIn(secret.encode().hex(), argv)

    def test_vault_diagnostic_cannot_echo_a_secret_to_caller(self):
        broken = self.root / 'broken-security'
        broken.write_text('#!' + sys.executable + '\nimport sys\nsys.stderr.write("CANARY-VAULT-ERROR")\nsys.exit(2)\n')
        broken.chmod(0o700)
        store = LoginStore(platform='darwin', binary=str(broken))
        with self.assertRaises(ValueError) as caught:
            store.add('example.com', 'alice', 'CANARY-VAULT-ERROR')
        self.assertNotIn('CANARY-VAULT-ERROR', str(caught.exception))

    def test_linux_secret_tool_stores_secret_on_stdin(self):
        binary = self.root / 'secret-tool'
        binary.write_text(FAKE_SECRET_TOOL.format(python=sys.executable))
        binary.chmod(0o700)
        store = LoginStore(platform='linux', binary=str(binary))
        self.assertTrue(store.available)
        secret = 'CANARY-LINUX-SECRET'
        item = store.add('example.com', 'alice', secret)
        self.assertEqual(store.get(item['id'])['password'], secret)
        self.assertEqual(store.list()[0]['username'], 'alice')
        self.assertNotIn(secret, self.log.read_text())
        store.delete(item['id'])
        self.assertEqual(store.list(), [])
        self.assertNotIn('__saved_logins__', self.vault.read_text())

    def test_unsupported_platform_is_unavailable(self):
        store = LoginStore(platform='unsupported', binary=str(self.binary))
        self.assertFalse(store.available)
        self.assertEqual(store.list(), [])


class FakeCDP:
    def __init__(self, url='https://example.com/login', username=True, password=True,
                 child_url=None):
        self.url = url
        self.username = username
        self.password = password
        self.child_url = child_url
        self.calls = []
        self.focused = None

    def call(self, method, params=None):
        params = params or {}
        self.calls.append((method, params))
        if method == 'Page.getFrameTree':
            tree = {'frame': {'id': 'frame', 'url': self.url}}
            if self.child_url:
                tree['childFrames'] = [{'frame': {'id': 'child', 'url': self.child_url}}]
            return {'frameTree': tree}
        if method == 'DOM.getDocument':
            return {'root': {'nodeId': 1}}
        if method == 'DOM.querySelectorAll':
            selector = params.get('selector', '').lower()
            if 'password' in selector:
                return {'nodeIds': [12] if self.password else []}
            return {'nodeIds': [11] if self.username else []}
        if method == 'DOM.describeNode':
            node_id = params.get('nodeId')
            if node_id == 11:
                return {'node': {'nodeId': 11, 'nodeName': 'INPUT',
                                 'attributes': ['type', 'email', 'autocomplete', 'username']}}
            if node_id == 12:
                return {'node': {'nodeId': 12, 'nodeName': 'INPUT',
                                 'attributes': ['type', 'password', 'autocomplete', 'current-password']}}
        if method == 'Page.createIsolatedWorld': return {'executionContextId': 7}
        if method == 'DOM.resolveNode': return {'object': {'objectId': 'node-' + str(params['nodeId'])}}
        if method == 'Runtime.callFunctionOn': return {'result': {'value': True}}
        if method == 'DOM.focus': self.focused = params['nodeId']
        if method == 'Runtime.evaluate': return {'result': {'objectId': 'active'}}
        if method == 'DOM.requestNode': return {'nodeId': self.focused}
        return {}

    def inserted(self):
        return [params['arguments'][0]['value'] for method, params in self.calls if method == 'Runtime.callFunctionOn']


class CDPFillTests(unittest.TestCase):
    LOGIN = {'site': 'example.com', 'username': 'alice@example.com',
             'password': 'CANARY-CDP-PASSWORD', 'subdomains': ['accounts.example.com']}

    def test_matching_https_page_uses_pinned_dom_nodes_without_focus(self):
        client = FakeCDP()
        fill_login(client, dict(self.LOGIN))
        self.assertEqual(client.inserted(), [self.LOGIN['username'], self.LOGIN['password']])
        self.assertFalse(any(m.startswith('Input.') or m == 'DOM.focus' for m, _ in client.calls))
        self.assertEqual([p['nodeId'] for m, p in client.calls if m == 'DOM.resolveNode'], [11, 12])

    def test_wrong_origin_or_insecure_page_never_receives_secret(self):
        for url in ('https://example.com.evil/login', 'https://evil.com/login',
                    'https://sub.example.com/login', 'http://example.com/login',
                    'https://accounts.example.com.evil/login', 'data:text/html,hello'):
            with self.subTest(url=url):
                client = FakeCDP(url=url)
                try: fill_login(client, dict(self.LOGIN))
                except (ValueError, RuntimeError): pass
                self.assertEqual(client.inserted(), [])

    def test_missing_top_level_fields_refuses_before_typing(self):
        for username, password in ((False, True), (True, False)):
            with self.subTest(username=username, password=password):
                client = FakeCDP(username=username, password=password)
                try: fill_login(client, dict(self.LOGIN))
                except (ValueError, RuntimeError): pass
                self.assertEqual(client.inserted(), [])

    def test_login_fields_in_cross_origin_iframe_are_not_used(self):
        client = FakeCDP(url='https://evil.com/', child_url='https://example.com/login',
                         username=False, password=False)
        try: fill_login(client, dict(self.LOGIN))
        except (ValueError, RuntimeError): pass
        self.assertEqual(client.inserted(), [])

    def test_loopback_http_is_allowed(self):
        for site in ('localhost:4444', '127.0.0.1:4444'):
            with self.subTest(site=site):
                client = FakeCDP(url='http://' + site + '/login')
                login = dict(self.LOGIN, site=site, subdomains=[])
                fill_login(client, login)
                self.assertEqual(client.inserted(), [login['username'], login['password']])

    def test_navigation_after_username_prevents_password_insert(self):
        class NavigatingCDP(FakeCDP):
            def call(self, method, params=None):
                if method == 'Page.getFrameTree' and self.inserted(): self.url = 'https://evil.com/'
                return super().call(method, params)
        client = NavigatingCDP()
        fill_login(client, dict(self.LOGIN))
        self.assertEqual(client.inserted(), [self.LOGIN['username']])

    def test_focus_moved_to_iframe_cannot_redirect_targeted_fill(self):
        class FocusStealingCDP(FakeCDP):
            def call(self, method, params=None):
                result = super().call(method, params)
                if method == 'DOM.focus': self.focused = 99  # iframe, not the pinned input
                return result
        client = FocusStealingCDP(child_url='https://evil.com/')
        self.assertIn('Filled', fill_login(client, dict(self.LOGIN)))
        self.assertEqual(client.inserted(), [self.LOGIN['username'], self.LOGIN['password']])
        self.assertIn('Page.createIsolatedWorld', [method for method, _ in client.calls])

    def test_focus_moved_after_keys_is_irrelevant_to_targeted_fill(self):
        class KeyStealingCDP(FakeCDP):
            def call(self, method, params=None):
                result = super().call(method, params)
                if method == 'Input.dispatchKeyEvent': self.focused = 99
                return result
        client = KeyStealingCDP(child_url='https://evil.com/')
        self.assertIn('Filled', fill_login(client, dict(self.LOGIN)))
        self.assertEqual(client.inserted(), [self.LOGIN['username'], self.LOGIN['password']])


class FakePipBrowser:
    def __init__(self):
        self.opens = []
        self.fills = []
        self.resets = 0

    def status(self):
        return {'available': True, 'running': True, 'profile': 'data/pip-browser-profile'}

    def open(self, site=None, **kwargs):
        self.opens.append(site)
        return self.status()

    def fill(self, login, **kwargs):
        self.fills.append(dict(login))
        return 'Filled'

    def reset(self):
        self.resets += 1
        return self.status()


class BrowserRouteTests(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    request = test_hub.HubCase.request
    login = test_hub.HubCase.login
    api = test_hub.HubCase.api

    def browser_message(self, payload):
        with self.h.lock:
            mid = self.h.add_message(self.cid, self.aid, 'assistant', BrowserCardParsingTests.fence(payload))
            self.h.db.commit()
        return mid

    def install_fake_saved_login(self):
        browser = FakePipBrowser()
        self.h._pip_browser = browser
        class FakeStore:
            available = True
            def list(self): return [{'id': 'login1', 'site': 'example.com',
                                     'username': 'alice', 'subdomains': []}]
            def get(self, identifier):
                if identifier != 'login1': raise AssertionError('wrong login')
                return {'id': identifier, 'site': 'example.com', 'username': 'alice',
                        'password': 'CANARY-RETRY-SECRET', 'subdomains': []}
        self.h._login_store = FakeStore()
        return browser

    def test_browser_routes_require_auth_and_reset_confirmation(self):
        self.assertEqual(self.request('/api/pip-browser')[0], 401)
        self.assertEqual(self.request('/api/saved-logins')[0], 401)
        self.cookie = self.login()
        browser = FakePipBrowser()
        self.h._pip_browser = browser
        self.assertEqual(self.api('/api/pip-browser')[0], 200)
        self.assertEqual(self.api('/api/pip-browser/reset', 'POST', {})[0], 400)
        self.assertEqual(browser.resets, 0)
        self.assertEqual(self.api('/api/pip-browser/reset', 'POST', {'confirm': True})[0], 200)
        self.assertEqual(browser.resets, 1)

    def test_saved_login_api_never_persists_password_in_hub(self):
        self.cookie = self.login()
        browser = FakePipBrowser()
        self.h._pip_browser = browser
        fake = self.root / 'security'
        fake.write_text(FAKE_SECURITY.format(python=sys.executable))
        fake.chmod(0o700)
        from unittest import mock
        vault = self.root / 'fake-vault.json'
        argv_log = self.root / 'fake-argv.jsonl'
        patch = mock.patch.dict(os.environ, {'FAKE_SECURITY_VAULT': str(vault),
                                             'FAKE_SECURITY_LOG': str(argv_log)})
        patch.start(); self.addCleanup(patch.stop)
        self.h._login_store = LoginStore(platform='darwin', binary=str(fake))
        secret = 'CANARY-HUB-DB-PASSWORD-2ff1'
        username = 'CANARY-USERNAME-2ff1@example.com'
        status, _, raw = self.api('/api/saved-logins/add', 'POST', {'site': 'example.com',
            'username': username, 'password': secret, 'subdomains': ['accounts.example.com']})
        self.assertEqual(status, 200, raw)
        status, _, raw = self.api('/api/saved-logins')
        self.assertEqual(status, 200, raw)
        listed = json.loads(raw)['logins']
        self.assertEqual(len(listed), 1)
        self.assertNotIn(secret, raw.decode())
        self.assertIn(secret, vault.read_text())
        mid = self.browser_message({'action': 'login_fill_request', 'site': 'example.com'})
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        logging.getLogger().addHandler(handler)
        try:
            status, _, raw = self.api('/api/browser-card', 'POST', {'message_id': mid, 'index': 0,
                'action': 'approve', 'login_id': listed[0]['id']})
        finally:
            logging.getLogger().removeHandler(handler)
        self.assertEqual(status, 200, raw)
        self.assertEqual(len(browser.fills), 1)
        self.assertEqual(browser.fills[0]['username'], username)
        self.assertEqual(browser.fills[0]['password'], secret)
        for row in self.h.db.execute('SELECT text FROM messages'):
            self.assertNotIn(secret, row['text'])
            self.assertNotIn(username, row['text'])
        for row in self.h.db.execute('SELECT prompt FROM jobs'):
            self.assertNotIn(secret, row['prompt'])
            self.assertNotIn(username, row['prompt'])
        self.assertNotIn(secret, log_stream.getvalue())
        self.assertNotIn(username, log_stream.getvalue())
        for path in self.h.data.rglob('*'):
            if path.is_file():
                contents = path.read_bytes()
                self.assertNotIn(secret.encode(), contents, str(path))
                self.assertNotIn(username.encode(), contents, str(path))
        with zipfile.ZipFile(io.BytesIO(hub_export.everything(self.h))) as archive:
            for name in archive.namelist():
                contents = archive.read(name)
                self.assertNotIn(secret.encode(), contents, name)
                self.assertNotIn(username.encode(), contents, name)
        self.assertNotIn(secret, argv_log.read_text())

    def test_browser_card_claims_fill_once_and_replies_to_requesting_pip(self):
        self.cookie = self.login()
        browser = FakePipBrowser()
        self.h._pip_browser = browser
        class FakeStore:
            available = True
            def list(self): return [{'id': 'login1', 'site': 'example.com',
                                     'username': 'alice', 'subdomains': []}]
            def get(self, identifier):
                if identifier != 'login1': raise AssertionError('wrong login')
                return {'id': identifier, 'site': 'example.com', 'username': 'alice',
                        'password': 'CANARY-FILL-SECRET', 'subdomains': []}
        self.h._login_store = FakeStore()
        mid = self.browser_message({'action': 'login_fill_request', 'site': 'example.com'})
        body = {'message_id': mid, 'index': 0, 'action': 'approve', 'login_id': 'login1'}
        first = self.api('/api/browser-card', 'POST', body)
        self.assertEqual(first[0], 200, first[2])
        second = self.api('/api/browser-card', 'POST', body)
        self.assertEqual(second[0], 200, second[2])
        self.assertEqual(len(browser.fills), 1)
        card = json.loads(self.h.db.execute('SELECT cards FROM messages WHERE id=?', (mid,)).fetchone()[0])[0]
        self.assertEqual(card['status'], 'filled')
        self.assertNotIn('CANARY-FILL-SECRET', json.dumps(card))
        reply = self.h.db.execute("SELECT * FROM messages WHERE role='user' AND reply_to=? ORDER BY id DESC LIMIT 1", (mid,)).fetchone()
        self.assertIsNotNone(reply)
        self.assertEqual(reply['chat_id'], self.cid)
        self.assertNotIn('CANARY-FILL-SECRET', reply['text'])

    def test_user_supplied_fence_does_not_become_a_browser_card(self):
        with self.h.lock:
            mid = self.h.add_message(self.cid, self.aid, 'user',
                                     BrowserCardParsingTests.fence({'action': 'signin_request',
                                         'site': 'example.com', 'reason': 'x'}))
            cards = json.loads(self.h.db.execute('SELECT cards FROM messages WHERE id=?', (mid,)).fetchone()[0])
        self.assertEqual(cards, [])

    def test_group_browser_result_returns_to_original_pip(self):
        self.cookie = self.login()
        self.h.create_agent({'name': 'Alpha', 'role': 'Test', 'model': 'haiku', 'draft_only': True})
        self.h.create_agent({'name': 'Beta', 'role': 'Test', 'model': 'haiku', 'draft_only': True})
        group = self.h.group({'name': 'Team', 'agents': ['alpha', 'beta']})['chat']['id']
        with self.h.lock:
            mid = self.h.add_message(group, 'beta', 'assistant',
                BrowserCardParsingTests.fence({'action': 'signin_request', 'site': 'example.com', 'reason': 'Check account'}))
            self.h.db.commit()
        status, _, raw = self.api('/api/browser-card', 'POST', {'message_id': mid, 'index': 0, 'action': 'done'})
        self.assertEqual(status, 200, raw)
        job = self.h.db.execute('SELECT agent_id,chat_id,reply_to FROM jobs ORDER BY id DESC LIMIT 1').fetchone()
        self.assertEqual(job['agent_id'], 'beta')
        self.assertEqual(job['chat_id'], group)
        reply = self.h.db.execute('SELECT reply_to FROM messages WHERE id=?', (job['reply_to'],)).fetchone()
        self.assertEqual(reply['reply_to'], mid)

    def test_interrupted_fill_claim_is_not_replayed(self):
        self.cookie = self.login()
        browser = FakePipBrowser()
        def interrupted(_login, **kwargs):
            browser.fills.append('attempt')
            raise KeyboardInterrupt('simulated process stop after claim')
        browser.fill = interrupted
        self.h._pip_browser = browser
        class FakeStore:
            available = True
            def list(self): return [{'id': 'login1', 'site': 'example.com', 'username': 'alice', 'subdomains': []}]
            def get(self, identifier): return {'id': identifier, 'site': 'example.com',
                                               'username': 'alice', 'password': 'secret', 'subdomains': []}
        self.h._login_store = FakeStore()
        mid = self.browser_message({'action': 'login_fill_request', 'site': 'example.com'})
        body = {'message_id': mid, 'index': 0, 'action': 'approve', 'login_id': 'login1'}
        with self.assertRaises(KeyboardInterrupt): self.h.browser_card(body)
        card = json.loads(self.h.db.execute('SELECT cards FROM messages WHERE id=?', (mid,)).fetchone()[0])[0]
        self.assertEqual(card['status'], 'filling')
        repeated = self.h.browser_card(body)
        self.assertTrue(repeated['duplicate'])
        self.assertEqual(browser.fills, ['attempt'])

    def test_failed_notification_reconciles_without_second_fill(self):
        browser = self.install_fake_saved_login()
        mid = self.browser_message({'action': 'login_fill_request', 'site': 'example.com'})
        body = {'message_id': mid, 'index': 0, 'action': 'approve', 'login_id': 'login1'}
        with mock.patch.object(self.h, 'send', side_effect=RuntimeError('simulated send failure')):
            with self.assertRaises(RuntimeError): self.h.browser_card(body)
        stored = json.loads(self.h.db.execute('SELECT cards FROM messages WHERE id=?', (mid,)).fetchone()[0])[0]
        self.assertEqual((stored['status'], stored['notification']), ('filled', 'pending'))
        self.h.reconcile_browser_notifications()
        stored = json.loads(self.h.db.execute('SELECT cards FROM messages WHERE id=?', (mid,)).fetchone()[0])[0]
        self.assertEqual(stored['notification'], 'sent')
        self.assertEqual(len(browser.fills), 1)
        reply = self.h.db.execute("SELECT request_id FROM messages WHERE role='user' AND reply_to=?", (mid,)).fetchone()
        self.assertEqual(reply['request_id'], 'browser-card-' + str(mid) + '-0-result')

    def test_restart_recovers_pending_notification_without_browser_action(self):
        browser = self.install_fake_saved_login()
        mid = self.browser_message({'action': 'login_fill_request', 'site': 'example.com'})
        body = {'message_id': mid, 'index': 0, 'action': 'approve', 'login_id': 'login1'}
        with mock.patch.object(self.h, 'send', side_effect=RuntimeError('simulated send failure')):
            with self.assertRaises(RuntimeError): self.h.browser_card(body)
        self.assertEqual(len(browser.fills), 1)
        old = self.h
        old.close()
        self.h = hub.Hub(self.root, old.config)
        self.addCleanup(self.h.close)
        card = json.loads(self.h.db.execute('SELECT cards FROM messages WHERE id=?', (mid,)).fetchone()[0])[0]
        self.assertEqual((card['status'], card['notification']), ('filled', 'sent'))
        self.assertEqual(self.h.db.execute("SELECT count(*) FROM messages WHERE role='user' AND reply_to=?", (mid,)).fetchone()[0], 1)
        self.assertEqual(len(browser.fills), 1)

    def test_post_send_crash_duplicate_tap_does_not_queue_again(self):
        browser = self.install_fake_saved_login()
        mid = self.browser_message({'action': 'login_fill_request', 'site': 'example.com'})
        body = {'message_id': mid, 'index': 0, 'action': 'approve', 'login_id': 'login1'}
        original_send = self.h.send
        def delivered_then_crash(payload):
            original_send(payload)
            raise RuntimeError('simulated crash before notification marker')
        with mock.patch.object(self.h, 'send', side_effect=delivered_then_crash):
            with self.assertRaises(RuntimeError): self.h.browser_card(body)
        before = self.h.db.execute('SELECT count(*) FROM jobs').fetchone()[0]
        repeated = self.h.browser_card(body)
        after = self.h.db.execute('SELECT count(*) FROM jobs').fetchone()[0]
        self.assertTrue(repeated['duplicate'])
        self.assertEqual(before, after)
        self.assertEqual(len(browser.fills), 1)
        self.assertEqual(self.h.db.execute("SELECT count(*) FROM messages WHERE role='user' AND reply_to=?", (mid,)).fetchone()[0], 1)

    def test_browser_cli_overrides_canonical_mcp_without_builtin_chrome(self):
        browser = FakePipBrowser()
        browser.ensure = lambda: ('http://127.0.0.1:4321',
                                  'ws://127.0.0.1:4321/devtools/browser/fake')
        self.h._pip_browser = browser
        agent = {'chrome': True, 'draft_only': False}
        with mock.patch('hub_browser.installed_mcp', return_value=('/fake/chrome-devtools-mcp', [])), mock.patch('hub_browser.pip_mcp_command', return_value=('/fake/node', ['/hub/hub_browser_mcp.mjs', '/private/pip/cdp.sock', '/fake/mcp.js', '--no-performance-crux'])):
            claude_flags, _ = self.h.browser_cli('claude', agent)
            codex_flags, _ = self.h.browser_cli('codex', agent)
        self.assertNotIn('--no-chrome', claude_flags)  # full-access Pips keep Claude in Chrome; Private Pips get --no-chrome
        self.assertNotIn('--chrome', claude_flags)
        config = json.loads(claude_flags[claude_flags.index('--mcp-config') + 1])
        self.assertEqual(set(config['mcpServers']), {'chrome-devtools'})
        args = config['mcpServers']['chrome-devtools']['args']
        self.assertIn('/private/pip/cdp.sock', args)
        self.assertNotIn('--browser-url=http://127.0.0.1:4321', args)
        self.assertEqual(claude_flags[claude_flags.index('--allowedTools') + 1], 'mcp__chrome-devtools__*')
        self.assertIn('--no-performance-crux', args)
        self.assertTrue(any(flag.startswith('mcp_servers.chrome-devtools={') and
                            'command="/fake/node"' in flag for flag in codex_flags))
        self.assertTrue(any('mcp_servers.chrome-devtools=' in flag and '/private/pip/cdp.sock' in flag
                            for flag in codex_flags))

    def test_codex_browser_config_flags_precede_prompt_separator(self):
        self.h.config['codex_bin'] = str(Path(__file__).with_name('fake_codex.py').resolve())
        self.h.config['detect_engines'] = False
        self.h.create_agent({'name': 'Coder', 'role': 'Code.', 'engine': 'codex',
                             'model': 'gpt-6.1-sol', 'chrome': True})
        browser = FakePipBrowser()
        browser.ensure = lambda: ('http://127.0.0.1:4321',
                                  'ws://127.0.0.1:4321/devtools/browser/fake')
        self.h._pip_browser = browser
        with mock.patch('hub_browser.installed_mcp', return_value=('/fake/chrome-devtools-mcp', [])), mock.patch('hub_browser.pip_mcp_command', return_value=('/fake/node', ['/hub/hub_browser_mcp.mjs', '/private/pip/cdp.sock', '/fake/mcp.js', '--no-performance-crux'])):
            jid = test_hub.HubCase.send(self, 'agent:coder', 'browse')['job_id']
            test_hub.HubCase.done(self, jid)
        calls = (self.root / 'agents' / 'coder' / 'fake_codex_calls.jsonl').read_text().splitlines()
        argv = json.loads(calls[0])['argv']
        separator = argv.index('--')
        self.assertTrue(any(arg.startswith('mcp_servers.chrome-devtools={') and
                            'command="/fake/node"' in arg for arg in argv[:separator]))
        self.assertTrue(any('/private/pip/cdp.sock' in arg for arg in argv[:separator]))
        self.assertNotIn('--chrome', argv)


class BrowserProfileTests(unittest.TestCase):
    def test_profile_path_is_fixed_and_symlink_is_refused(self):
        from hub_browser import PipBrowser
        with tempfile.TemporaryDirectory(prefix='hub-browser-profile-') as tmp:
            root = Path(tmp)
            data = root / 'data'; data.mkdir()
            outside = root / 'outside'; outside.mkdir()
            (outside / 'keep').write_text('keep')
            browser = PipBrowser(data, {'pip_browser_profile': str(outside)})
            self.assertEqual(browser.profile, data / 'pip-browser-profile')
            browser.profile.symlink_to(outside, target_is_directory=True)
            with self.assertRaises((OSError, ValueError)):
                browser._profile(create=True)
            self.assertEqual((outside / 'keep').read_text(), 'keep')

    def test_reset_refuses_live_singleton_lock_when_endpoint_unavailable(self):
        with tempfile.TemporaryDirectory(prefix='hub-browser-profile-') as tmp:
            root = Path(tmp)
            data = root / 'data'; data.mkdir()
            profile = data / 'pip-browser-profile'; profile.mkdir()
            (profile / 'keep').write_text('keep')
            (profile / 'SingletonLock').symlink_to('host-' + str(os.getpid()))
            browser = PipBrowser(data)
            self.assertIsNone(browser._endpoint())
            with self.assertRaises(CDPError): browser.reset()
            self.assertEqual((profile / 'keep').read_text(), 'keep')
            self.assertTrue((profile / 'SingletonLock').is_symlink())


if __name__ == '__main__':
    unittest.main()
