"""Full access CLI permissions and settings; deterministic fake CLIs only."""
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest import mock

import hub
from hub_access import APPROVAL_RULE, codex_exec_command
from hub_process import OutputLimitExceeded
import test_hub
from test_engines import FAKE_CODEX


AUTO_HELP = ('--permission-mode <mode> Permission mode\n'
             '  (choices: "default", "acceptEdits", "auto", "plan")\n'
             '--include-partial-messages')
FALLBACK = ['--permission-mode', 'acceptEdits', '--allowedTools', 'WebSearch,WebFetch']


class FullAccessPermissions(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    send = test_hub.HubCase.send
    done = test_hub.HubCase.done
    calls = test_hub.HubCase.calls
    responses = test_hub.HubCase.responses
    login = test_hub.HubCase.login
    api = test_hub.HubCase.api
    request = test_hub.HubCase.request

    def codex_calls(self, aid):
        folder = Path(self.h.agents()[aid]['path'])
        return [json.loads(line) for line in (folder / 'fake_codex_calls.jsonl').read_text().splitlines()]

    def test_full_access_auto_probe_uses_permission_choices_and_caches_per_binary(self):
        cases = [(AUTO_HELP, True),
                 ('--permission-mode <mode> (choices: "default", "acceptEdits", "plan")', False),
                 ('--permission-mode <mode> (choices: "automatic", "plan")', False),
                 ('--permission-mode <mode> Mode\n--other (choices: "auto")', False),
                 ('--auto-update --permission-mode <mode> No choices listed', False)]
        for index, (help_text, supported) in enumerate(cases):
            with self.subTest(help=help_text):
                result = subprocess.CompletedProcess([], 0, help_text, '')
                with mock.patch('hub_isolation.run_bounded', return_value=result) as probe:
                    binary = 'fake-claude-' + str(index)
                    expected = ['--permission-mode', 'auto'] if supported else FALLBACK
                    for _ in range(2): self.assertEqual(self.h.claude_full_access_flags(binary), expected)
                    probe.assert_called_once()
                    self.assertEqual(probe.call_args.args[0], [binary, '--help'])
                    self.assertEqual(probe.call_args.kwargs['timeout'], 5)

    def test_full_access_auto_probe_failure_uses_cached_fallback(self):
        failures = [OSError('missing'), subprocess.TimeoutExpired('claude', 5), OutputLimitExceeded()]
        for index, failure in enumerate(failures):
            with self.subTest(failure=type(failure).__name__):
                with mock.patch('hub_isolation.run_bounded', side_effect=failure) as probe:
                    for _ in range(2):
                        self.assertEqual(self.h.claude_full_access_flags('failed-' + str(index)), FALLBACK)
                    probe.assert_called_once()
        with mock.patch('hub_isolation.run_bounded', return_value=subprocess.CompletedProcess([], 1, AUTO_HELP, '')):
            self.assertEqual(self.h.claude_full_access_flags('nonzero'), FALLBACK)

    def test_full_access_claude_auto_new_and_resumed_arguments(self):
        for text in ('first', 'second'): self.done(self.send(text=text)['job_id'])
        for call in self.calls():
            args = call['argv']
            self.assertEqual(args[args.index('--permission-mode') + 1], 'auto')
            self.assertEqual(args.count('--permission-mode'), 1)
            self.assertIn('--chrome', args)
            for flag in ('--allowedTools', '--safe-mode', '--tools', '--dangerously-skip-permissions', 'bypassPermissions'):
                self.assertNotIn(flag, args)
            system = args[args.index('--append-system-prompt') + 1]
            self.assertIn(APPROVAL_RULE, system)
            self.assertNotIn('tools are unavailable', system.lower())
            self.assertNotIn('do not claim browser tools are available', system.lower())
        self.assertIn('--resume', self.calls()[-1]['argv'])

    def test_full_access_claude_unsupported_auto_allows_web_and_edits(self):
        self.h._claude_auto_support = {str(test_hub.FAKE): False}
        for text in ('first', 'second'): self.done(self.send(text=text)['job_id'])
        for call in self.calls():
            args = call['argv']
            self.assertEqual(args[args.index('--permission-mode') + 1], 'acceptEdits')
            self.assertEqual(args[args.index('--allowedTools') + 1], 'WebSearch,WebFetch')
            self.assertIn('--chrome', args)
            self.assertNotIn('bypassPermissions', args)
            self.assertNotIn('--dangerously-skip-permissions', args)
        self.assertIn('--resume', self.calls()[-1]['argv'])

    def test_full_access_fallback_preserves_pip_browser_allow_rule(self):
        self.h._claude_auto_support = {str(test_hub.FAKE): False}
        flags = ['--mcp-config', '{"mcpServers":{}}', '--allowedTools', 'mcp__chrome-devtools__*']
        with mock.patch.object(self.h, 'browser_cli', return_value=(flags, 'Use your browser tools.')):
            self.done(self.send(text='browse')['job_id'])
        args = self.calls()[-1]['argv']
        self.assertEqual(args.count('--allowedTools'), 1)
        self.assertEqual(args[args.index('--allowedTools') + 1], 'WebSearch,WebFetch,mcp__chrome-devtools__*')
        self.assertEqual(flags[-2:], ['--allowedTools', 'mcp__chrome-devtools__*'])

    def test_full_access_inherit_omits_flags_and_starts_fresh_session(self):
        self.done(self.send(text='auto')['job_id'])
        self.h.save_settings({'full_access_permission_mode': 'inherit'})
        with mock.patch.object(self.h, 'claude_full_access_flags', wraps=self.h.claude_full_access_flags) as flags:
            for text in ('inherit', 'resume inherit'): self.done(self.send(text=text)['job_id'])
            self.assertEqual(flags.call_count, 2)
        for call in self.calls()[1:]:
            args = call['argv']
            self.assertNotIn('--permission-mode', args)
            self.assertNotIn('--allowedTools', args)
            self.assertIn('--chrome', args)
        self.assertNotIn('--resume', self.calls()[1]['argv'])
        self.assertIn('--resume', self.calls()[2]['argv'])
        self.h.save_settings({'full_access_permission_mode': 'auto'})
        self.done(self.send(text='auto again')['job_id'])
        self.assertNotIn('--resume', self.calls()[-1]['argv'])
        self.assertEqual(self.calls()[-1]['argv'][self.calls()[-1]['argv'].index('--permission-mode') + 1], 'auto')
        with mock.patch('hub_isolation.run_bounded') as probe:
            self.h.config['full_access_permission_mode'] = 'inherit'
            self.assertEqual(self.h.claude_full_access_flags('unprobed'), [])
            probe.assert_not_called()

    def test_full_access_setting_default_persistence_and_validation(self):
        self.cookie = self.login()
        status, _, payload = self.api('/api/settings')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)['full_access_permission_mode'], 'auto')
        status, _, payload = self.api('/api/settings', 'POST', {'full_access_permission_mode': 'inherit'})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)['full_access_permission_mode'], 'inherit')
        saved = json.loads((self.root / 'config.json').read_text())
        self.assertEqual(saved['full_access_permission_mode'], 'inherit')
        for invalid in ('bypassPermissions', 'acceptEdits', '', None, True, [], {}):
            status, _, _ = self.api('/api/settings', 'POST', {'full_access_permission_mode': invalid})
            self.assertEqual(status, 400)
            self.assertEqual(json.loads((self.root / 'config.json').read_text()), saved)
        self.h.close()
        self.h = hub.Hub(self.root, saved, defer_token=True)
        self.addCleanup(self.h.close)
        self.assertEqual(self.h.feature_settings()['full_access_permission_mode'], 'inherit')

    def test_full_access_setting_keeps_claude_private_and_draft_flags(self):
        for mode in ('auto', 'inherit'):
            self.h.save_settings({'full_access_permission_mode': mode})
            for private, draft in ((True, False), (False, True), (True, True)):
                with self.subTest(mode=mode, private=private, draft=draft):
                    self.h.edit_agent({'id': self.aid, 'private_pip': private, 'draft_only': draft})
                    with mock.patch.object(self.h, 'claude_full_access_flags') as full:
                        self.done(self.send(text='restricted')['job_id'])
                        full.assert_not_called()
                    args = self.calls()[-1]['argv']
                    self.assertIn('--safe-mode', args)
                    self.assertIn('--no-chrome', args)
                    self.assertNotIn('--chrome', args)
                    self.assertNotIn('--allowedTools', args)
                    self.assertEqual(args[args.index('--permission-mode') + 1], 'plan' if draft else 'auto')
                    if draft:
                        self.assertEqual(args[args.index('--tools') + 1], 'Read,Glob,Grep')
                        self.assertEqual(args[args.index('--disallowedTools') + 1], 'Bash,Write,Edit,MultiEdit,NotebookEdit,Agent,Task')
                        self.assertIn('--strict-mcp-config', args)
                    else:
                        self.assertNotIn('--tools', args)
                        self.assertNotIn('--strict-mcp-config', args)

    def test_full_access_codex_sandbox_and_approval_options_precede_exec_and_resume(self):
        for sid in ('', 'thread-id'):
            args = codex_exec_command('codex', sid)
            self.assertEqual(args[:6], ['codex', '-s', 'workspace-write', '-c', 'approval_policy="never"', 'exec'])
            self.assertEqual(args[6:], ['resume', sid] if sid else [])
            for private, draft, flags in ((True, False, []), (False, True, ['-s', 'read-only']),
                                          (True, True, ['-s', 'read-only'])):
                args = codex_exec_command('codex', sid, draft, private)
                self.assertEqual(args, ['codex'] + flags + ['exec'] + (['resume', sid] if sid else []))

    def test_full_access_setting_only_changes_claude_session_policy(self):
        codex = {'engine': 'codex'}
        before = self.h.rules_policy(codex)
        claude = self.h.rules_policy(codex, 'claude')
        self.h.config['full_access_permission_mode'] = 'inherit'
        self.assertEqual(self.h.rules_policy(codex), before)
        self.assertNotEqual(self.h.rules_policy(codex, 'claude'), claude)
        self.assertEqual(self.h.rules_policy({'private_pip': True}), 'access-v24-browser-private')
        self.assertEqual(self.h.rules_policy({'draft_only': True}), 'access-v24-browser-full-draft')

    def test_full_access_codex_preserves_environment_network_and_working_folder(self):
        self.h.config['codex_bin'] = str(FAKE_CODEX)
        account = Path(os.environ['CODEX_HOME'])
        config = 'sandbox_mode = "read-only"\napproval_policy = "on-request"\n[sandbox_workspace_write]\nnetwork_access = true\n'
        (account / 'config.toml').write_text(config)
        folder = self.root / 'coding-work'
        folder.mkdir()
        aid = self.h.create_agent({'name': 'Permission Coder', 'role': 'Build.', 'engine': 'codex', 'workdir': str(folder)})['agent']['id']
        for text in ('first', 'second'): self.done(self.send('agent:' + aid, text)['job_id'])
        calls = [json.loads(line) for line in (folder / 'fake_codex_calls.jsonl').read_text().splitlines()]
        for call in calls:
            args = call['argv']
            self.assertEqual(args[:5], ['-s', 'workspace-write', '-c', 'approval_policy="never"', 'exec'])
            self.assertEqual(call['cwd'], str(folder))
            self.assertEqual(call['codex_home'], str(account))
            self.assertEqual(call['config'], config)
            self.assertNotIn('network_access=', ' '.join(args))
            self.assertNotIn('danger-full-access', args)
            self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', args)
            self.assertIn(APPROVAL_RULE, args[-1])
        self.assertIn('resume', calls[-1]['argv'])

    def test_full_access_denied_tool_reply_stays_visible(self):
        denied = 'WebSearch was denied permission in this session.'
        self.responses(self.aid, [{'result': denied}])
        self.done(self.send(text='Search the web')['job_id'])
        replies = [message for message in self.h.history(self.cid)['messages'] if message['role'] == 'assistant']
        self.assertEqual(replies[-1]['text'], denied)


if __name__ == '__main__': unittest.main()
