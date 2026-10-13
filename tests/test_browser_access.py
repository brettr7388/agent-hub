"""Browser/permissions regressions; fake CDP and CLIs only."""
import contextlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import hub
import hub_guide
from hub_access import codex_exec_command
from hub_browser import PipBrowser, parse_browser_cards
from hub_cdp import FILLED, fill_login, origin_matches
from hub_login import _host, login_allows_site, validate_site
from test_pip_browser import FakeCDP, FakePipBrowser
import test_hub


class FakeBroker:
    def __init__(self, pages=()):
        self.pages = list(pages)
        self.calls = []
        self.sessions = []
        self.running = True
        self.socket_path = '/private/pip/cdp.sock'
        self.process = None

    def connect(self, target_id=None):
        if target_id:
            self.sessions.append(target_id)
            return contextlib.nullcontext(FakeCDP(url=next(p['url'] for p in self.pages if p['targetId'] == target_id)))
        return self

    def __enter__(self): return self
    def __exit__(self, *args): pass
    def close(self): self.running = False

    def call(self, method, params=None):
        self.calls.append((method, params or {}))
        if method == 'Target.getTargets': return {'targetInfos': self.pages}
        if method == 'Target.createTarget':
            page = {'targetId': 'new-' + str(len(self.pages)), 'type': 'page', 'url': params['url']}
            self.pages.append(page)
            return {'targetId': page['targetId']}
        return {}


def page(identifier, url):
    return {'targetId': identifier, 'type': 'page', 'url': url}


class BrowserNavigationTests(unittest.TestCase):
    def browser(self, pages=()):
        browser = PipBrowser(Path('/unused'))
        browser.broker = FakeBroker(pages)
        browser.ensure = lambda: (None, browser.broker.socket_path)
        browser._front = lambda: None
        browser._binary = lambda: '/fake/chrome'
        return browser

    def test_uc1_f3_local_port_is_preserved_and_open_reuses_the_login_tab(self):
        browser = self.browser()
        browser.open('127.0.0.1:4841', requester='inboxer')
        browser.open('127.0.0.1:4841', requester='inboxer')
        self.assertEqual([p['url'] for p in browser.broker.pages], ['http://127.0.0.1:4841'])
        self.assertEqual(sum(m == 'Target.createTarget' for m, p in browser.broker.calls), 1)

    def test_open_preserves_existing_login_path_and_settings_reuses_page(self):
        browser = self.browser([page('login', 'http://localhost:4841/login?next=inbox')])
        browser.open('localhost:4841')
        browser.open()
        self.assertEqual(browser.broker.pages[0]['url'], 'http://localhost:4841/login?next=inbox')
        self.assertFalse(any(m == 'Target.createTarget' for m, p in browser.broker.calls))

    def test_uc1_f4_fill_targets_requesting_pip_login_tab_even_if_another_is_focused(self):
        browser = self.browser([page('login', 'https://example.com/login'), page('unrelated', 'https://other.com/')])
        browser.open('example.com', requester='pip1')
        login = {'site': 'example.com', 'subdomains': [], 'username': 'alice', 'password': 'canary'}
        self.assertEqual(browser.fill(login, requester='pip1', site='example.com'), FILLED)
        self.assertEqual(browser.broker.sessions, ['login'])

    def test_pinned_target_navigation_never_falls_back_to_another_matching_tab(self):
        browser = self.browser([page('login', 'https://example.com/login')])
        browser.open('example.com', requester='pip1')
        browser.broker.pages[0]['url'] = 'https://evil.com/'
        browser.broker.pages.append(page('other', 'https://example.com/login'))
        result = browser.fill({'site': 'example.com', 'subdomains': [], 'username': 'a', 'password': 'secret'}, requester='pip1')
        self.assertIn('login tab navigated away', result)
        self.assertIn('refused', result)
        self.assertEqual(browser.broker.sessions, [])

    def test_unpinned_ambiguous_tab_refuses_precisely(self):
        browser = self.browser([page('one', 'https://example.com/login'), page('two', 'https://example.com/login')])
        result = browser.fill({'site': 'example.com', 'username': 'a', 'password': 'secret'})
        self.assertIn('Multiple Pip tabs', result)
        self.assertEqual(browser.broker.sessions, [])

    def test_subdomain_fill_is_bound_to_requested_site(self):
        browser = self.browser([page('base', 'https://example.com/login'), page('accounts', 'https://accounts.example.com/login')])
        browser.open('accounts.example.com', requester='pip1')
        result = browser.fill({'site': 'example.com', 'subdomains': ['accounts.example.com'], 'username': 'a', 'password': 'secret'}, requester='pip1', site='accounts.example.com')
        self.assertEqual(result, FILLED)
        self.assertEqual(browser.broker.sessions, ['accounts'])

    def test_base_site_login_redirect_to_explicit_saved_subdomain_is_allowed(self):
        browser = self.browser([page('login', 'https://example.com/login')])
        browser.open('example.com', requester='pip1')
        browser.broker.pages[0]['url'] = 'https://accounts.example.com/login'
        result = browser.fill({'site': 'example.com', 'subdomains': ['accounts.example.com'], 'username': 'a', 'password': 'secret'}, requester='pip1', site='example.com')
        self.assertEqual(result, FILLED)
        self.assertEqual(browser.broker.sessions, ['login'])

    def test_navigation_during_attach_to_other_allowed_subdomain_is_refused(self):
        browser = self.browser([page('accounts', 'https://accounts.example.com/login')])
        browser.open('accounts.example.com', requester='pip1')
        original = browser.broker.connect
        attached = []
        def connect(target=None):
            if target:
                client = FakeCDP(url='https://example.com/login')
                attached.append(client)
                return contextlib.nullcontext(client)
            return original()
        browser.broker.connect = connect
        result = browser.fill({'site': 'example.com', 'subdomains': ['accounts.example.com'], 'username': 'a', 'password': 'secret'}, requester='pip1', site='accounts.example.com')
        self.assertIn('refused', result)
        self.assertEqual(attached[0].inserted(), [])


    def test_sec01_existing_profile_permissions_are_made_owner_only(self):
        with tempfile.TemporaryDirectory(dir=str(Path('/tmp').resolve())) as temp:
            data = Path(temp)
            browser = PipBrowser(data)
            browser.profile.mkdir(mode=0o755)
            browser._profile()
            self.assertEqual(browser.profile.stat().st_mode & 0o777, 0o700)

    def test_reopening_closed_browser_cleans_previous_private_transport(self):
        with tempfile.TemporaryDirectory(dir=str(Path('/tmp').resolve())) as temp:
            browser = PipBrowser(Path(temp))
            browser._binary = lambda: '/fake/chrome'
            dead = mock.Mock(running=False)
            browser.broker = dead
            fresh = FakeBroker()
            with mock.patch('hub_browser.PipeBroker.launch', return_value=fresh):
                self.assertEqual(browser.ensure(), (None, fresh.socket_path))
            dead.close.assert_called_once()
            browser.close()


class BrowserValidationTests(unittest.TestCase):
    def test_uc1_f6_local_host_port_gets_a_signin_card(self):
        for site in ('localhost:4841', '127.0.0.1:4841'):
            clean, cards = parse_browser_cards('```agent-hub\n' + json.dumps({'action': 'signin_request', 'site': site, 'reason': 'read inbox'}) + '\n```')
            self.assertEqual(clean, '')
            self.assertEqual(cards[0]['site'], site)
            self.assertEqual(validate_site(site), site)
        for site in ('localhost:0', 'localhost:65536', 'example.com:443', '127.0.0.1:4841/path', 'localhost:4841:9'):
            with self.subTest(site=site), self.assertRaises(ValueError): _host(site)

    def test_local_saved_port_is_exact_and_legacy_bare_host_cannot_fill(self):
        login = {'site': 'localhost:4841', 'username': 'a', 'password': 'canary'}
        self.assertTrue(origin_matches('http://localhost:4841/login', login))
        self.assertFalse(origin_matches('http://localhost:4842/login', login))
        self.assertFalse(login_allows_site(login, 'localhost:4842'))
        self.assertFalse(login_allows_site(dict(login, site='localhost'), 'localhost:4841'))
        self.assertFalse(login_allows_site(dict(login, site='localhost'), '127.0.0.1:4841'))

    def test_sec02_replaced_node_is_refused_in_same_operation(self):
        class Replaced(FakeCDP):
            def call(self, method, params=None):
                if method == 'Runtime.callFunctionOn':
                    self.calls.append((method, params))
                    return {'result': {'value': False}}
                return super().call(method, params)
        client = Replaced()
        result = fill_login(client, {'site': 'example.com', 'username': 'a', 'password': 'canary'})
        self.assertIn('top-level document changed', result)
        self.assertEqual(len(client.inserted()), 1)  # username attempted, no password released
        self.assertFalse(any(m.startswith('Input.') or m == 'DOM.focus' for m, _ in client.calls))


class BrowserPermissionsTests(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    send = test_hub.HubCase.send
    done = test_hub.HubCase.done
    calls = test_hub.HubCase.calls

    def test_uc1_f1_uc3_p12_sealed_modes_reject_browser_creation_and_explicit_edit(self):
        for mode in ('private_pip', 'draft_only'):
            with self.subTest(mode=mode), self.assertRaisesRegex(hub.HubError, 'Pip browser requires'):
                self.h.create_agent({'name': 'Sealed ' + mode, 'role': 'test', 'chrome': True, mode: True})
            with self.subTest(mode=mode), self.assertRaisesRegex(hub.HubError, 'Pip browser requires'):
                self.h.edit_agent({'id': 'assistant', 'chrome': True, mode: True})
            with mock.patch('hub_browser.installed_mcp') as resolver:
                flags, prompt = self.h.browser_cli('claude', {'chrome': True, mode: True})
            resolver.assert_not_called()
            self.assertIn('disabled', prompt)
            self.assertNotIn('--mcp-config', flags)

    def test_browser_preference_is_respected_and_turning_private_on_clears_it(self):
        created = self.h.create_agent({'name': 'Browser', 'role': 'test', 'chrome': True})['agent']
        self.assertTrue(created['chrome'])
        updated = self.h.edit_agent({'id': created['id'], 'chrome': False})['agent']
        self.assertFalse(updated['chrome'])
        self.h.edit_agent({'id': created['id'], 'chrome': True})
        self.h.edit_agent({'id': created['id'], 'private_pip': True})
        self.assertFalse(self.h.agents()[created['id']]['chrome'])
        self.h.edit_agent({'id': created['id'], 'private_pip': False})
        self.assertFalse(self.h.agents()[created['id']]['chrome'])

    def test_uc1_f2_uc3_p11_only_hub_browser_tools_are_preapproved_per_run(self):
        browser = FakePipBrowser()
        browser.ensure = lambda: (None, '/private/pip/cdp.sock')
        self.h._pip_browser = browser
        with mock.patch('hub_browser.installed_mcp', return_value=('/fake/mcp', [])), mock.patch('hub_browser.pip_mcp_command', return_value=('/fake/node', ['bridge.mjs', '/private/pip/cdp.sock', 'mcp.js'])):
            claude, _ = self.h.browser_cli('claude', {'chrome': True})
            codex, _ = self.h.browser_cli('codex', {'chrome': True})
            off, _ = self.h.browser_cli('claude', {'chrome': False})
        self.assertEqual(claude[claude.index('--allowedTools') + 1], 'mcp__chrome-devtools__*')
        self.assertNotIn('--permission-mode', claude)
        self.assertNotIn('--dangerously-skip-permissions', claude)
        config = json.loads(claude[claude.index('--mcp-config') + 1])
        self.assertEqual(list(config['mcpServers']), ['chrome-devtools'])
        self.assertEqual(off, [])
        self.assertIn('mcp_servers.chrome-devtools=', codex[1])
        self.assertIn('default_tools_approval_mode="approve"', codex[1])
        self.assertNotIn('approval_policy=', codex[1])
        self.assertNotIn('--browser-url', codex[1])

    def test_missing_browser_tools_fail_visibly_instead_of_a_silent_no_tools_turn(self):
        with mock.patch('hub_browser.installed_mcp', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'not installed locally'):
                self.h.browser_cli('claude', {'chrome': True})

    def test_successful_signin_open_tap_can_reopen_existing_tab(self):
        browser = FakePipBrowser()
        self.h._pip_browser = browser
        mid = self.h.add_message(self.cid, self.aid, 'assistant', '```agent-hub\n' + json.dumps({'action': 'signin_request', 'site': 'localhost:4841', 'reason': 'sign in'}) + '\n```')
        self.h.db.commit()
        body = {'message_id': mid, 'index': 0, 'action': 'open'}
        for _ in range(2):
            self.assertEqual(self.h.browser_card(body)['card']['status'], 'opened')
        self.assertEqual(browser.opens, ['localhost:4841', 'localhost:4841'])

    def test_fake_claude_new_and_resume_turns_receive_only_browser_allow_rule(self):
        agent = self.h.create_agent({'name': 'Web Pip', 'role': 'test', 'chrome': True})['agent']
        browser = FakePipBrowser()
        browser.ensure = lambda: (None, '/private/pip/cdp.sock')
        self.h._pip_browser = browser
        with mock.patch('hub_browser.installed_mcp', return_value=('/fake/mcp', [])), mock.patch('hub_browser.pip_mcp_command', return_value=('/fake/node', ['bridge.mjs', '/private/pip/cdp.sock', 'mcp.js'])):
            for text in ('first', 'second'): self.done(self.send('agent:' + agent['id'], text)['job_id'])
        calls = self.calls(agent['id'])
        for call in calls:
            args = call['argv']
            self.assertEqual(args[args.index('--allowedTools') + 1], 'mcp__chrome-devtools__*')
            self.assertIn('--chrome', args)
            self.assertEqual(args[args.index('--permission-mode') + 1], 'auto')
        self.assertIn('--resume', calls[-1]['argv'])

    def test_sec_agents01_codex_read_only_option_precedes_exec_even_for_resume(self):
        fake = str(Path(__file__).with_name('fake_codex.py'))
        for sid in ('', 'fake-thread'):
            args = codex_exec_command(fake, sid, True)
            self.assertEqual(args[1:4], ['-s', 'read-only', 'exec'])
            with tempfile.TemporaryDirectory(dir=str(Path('/tmp').resolve())) as temp:
                result = subprocess.run(args + ['--json', '--', 'test'], cwd=temp, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            if sid: self.assertIn('resume', args)

    def test_uc3_p22_guide_proposal_uses_hub_model_defaults_and_keeps_browser_choice(self):
        self.h.config['default_model'] = 'opus'
        self.h.config['default_codex_model'] = 'gpt-6-astra'
        for engine, expected in (('claude', 'opus'), ('codex', 'gpt-6-astra')):
            spec = {'action': 'create_agent', 'name': 'Browser ' + engine, 'instructions': 'test', 'engine': engine, 'chrome': True}
            proposal = hub_guide.proposal(self.h, spec)
            self.assertEqual(proposal['model'], expected)
            self.assertTrue(proposal['chrome'])
            created = self.h._create_guide_proposal(proposal)['agent']
            self.assertEqual(created['model'], expected)
            self.assertTrue(created['chrome'])
