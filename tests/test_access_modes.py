"""Access defaults, private modes and linked overlays; fake CLIs only."""
import json
import os
from pathlib import Path
import unittest
from unittest import mock

import hub
from hub_access import APPROVAL_RULE
import test_hub
from test_engines import FAKE_CODEX


class AccessModes(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    send = test_hub.HubCase.send
    done = test_hub.HubCase.done
    calls = test_hub.HubCase.calls
    login = test_hub.HubCase.login
    api = test_hub.HubCase.api
    request = test_hub.HubCase.request

    def codex_calls(self, aid):
        path = Path(self.h.agents()[aid]['path']) / 'fake_codex_calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_all_default_claude_pips_keep_normal_configuration(self):
        aid = self.h.create_agent({'name': 'Fresh', 'role': 'Help.'})['agent']['id']
        for pip in ('guide', 'assistant', aid):
            agent = self.h.agents()[pip]
            self.assertFalse(agent['private_pip'])
            self.assertFalse(agent['draft_only'])
            self.assertTrue(agent['use_global_rules'])
            self.done(self.send('agent:' + pip, 'hello')['job_id'])
            args = self.calls(pip)[-1]['argv']
            self.assertIn('--chrome', args)
            self.assertEqual(args[args.index('--permission-mode') + 1], 'auto')
            for forbidden in ('--safe-mode', '--strict-mcp-config', '--tools', '--allowedTools', '--setting-sources'):
                self.assertNotIn(forbidden, args)
            self.assertIn(APPROVAL_RULE, args[args.index('--append-system-prompt') + 1])

    def test_normal_environment_keeps_plugins_credentials_and_proxies(self):
        marker = {'HTTPS_PROXY': 'http://proxy.invalid:8080', 'MY_MCP_AUTH': 'fake-test-auth',
                  'CUSTOM_PLUGIN_PATH': '/tmp/fake-plugin'}
        with mock.patch.dict(os.environ, marker):
            original = hub.start_process
            with mock.patch('hub.start_process', wraps=original) as launched:
                self.done(self.send(text='with integrations')['job_id'])
            env = launched.call_args.kwargs['env']
            for name, value in marker.items(): self.assertEqual(env[name], value)
            self.assertEqual(env['HOME'], os.environ['HOME'])
            self.assertEqual(env['PATH'], os.environ['PATH'])

    def test_team_workers_launch_normally_in_their_working_folder(self):
        self.h.config['codex_bin'] = str(FAKE_CODEX)
        for engine in ('claude', 'codex'):
            folder = self.root / ('work-' + engine)
            folder.mkdir()
            (folder / '.git').write_text('gitdir: nonexistent\n')
            with mock.patch.object(self.h, 'enqueue'):
                result = self.h.create_swarm({'goal': 'Check the project', 'shape': 'partition', 'working_dir': str(folder),
                    'workers': [{'role': 'Checker', 'slice': 'Check.', 'engine': engine}]})
            worker = result['workers'][0]
            agent = self.h.agents()[worker['agent_id']]
            self.assertFalse(agent['private_pip'])
            self.assertFalse(agent['draft_only'])
            self.h.execute(worker['job_id'])
            log = folder / ('fake_calls.jsonl' if engine == 'claude' else 'fake_codex_calls.jsonl')
            call = json.loads(log.read_text().splitlines()[-1])
            self.assertEqual(call['cwd'], str(folder))
            self.assertNotIn('--safe-mode', call['argv'])
            self.assertNotIn('--ignore-user-config', call['argv'])
            if engine == 'claude': self.assertIn('--chrome', call['argv'])
            else: self.assertEqual(call['codex_home'], os.environ['CODEX_HOME'])

    def test_guide_upgrade_changes_its_old_default_once_and_preserves_user_choice(self):
        old = 'You are draft-only: never create, edit, run, or contact anything yourself. The Hub presents your proposals for owner approval.'
        self.h.edit_agent({'id': 'guide', 'draft_only': True,
                          'role': 'You are Guide, the Agent Hub starter. ' + old})
        self.h._put_setting('guide_access_v22', False)
        self.h.db.commit()
        self.h.ensure_guide()
        self.assertFalse(self.h.agents()['guide']['draft_only'])
        self.assertNotIn(old, self.h.agents()['guide']['role'])
        self.h.edit_agent({'id': 'guide', 'draft_only': True})
        self.h.ensure_guide()
        self.assertTrue(self.h.agents()['guide']['draft_only'])

    def test_guide_creation_preserves_user_selected_modes(self):
        spec = {'action': 'create_agent', 'name': 'Clean Writer', 'instructions': 'Write.',
                'private_pip': True, 'draft_only': True}
        mid = self.h.add_message(self.h.guide_chat(), self.h.guide_id(), 'assistant',
            '```agent-hub\n' + json.dumps(spec) + '\n```')
        self.h.db.commit()
        response = self.h.guide_proposal({'message_id': mid, 'index': 0, 'action': 'create'})
        self.assertTrue(response['result']['agent']['private_pip'])
        self.assertTrue(response['result']['agent']['draft_only'])

    def test_codex_defaults_use_original_home_and_config_then_private_and_back(self):
        self.h.config['codex_bin'] = str(FAKE_CODEX)
        account = Path(os.environ['CODEX_HOME'])
        config = 'model = "gpt-6.1-sol"\n# User MCP and plugins are preserved\n'
        (account / 'config.toml').write_text(config)
        aid = self.h.create_agent({'name': 'Coder', 'role': 'Build.', 'engine': 'codex'})['agent']['id']
        for text in ('one', 'two'): self.done(self.send('agent:' + aid, text)['job_id'])
        for call in self.codex_calls(aid):
            args = call['argv']
            self.assertEqual(call['home'], os.environ['HOME'])
            self.assertEqual(call['codex_home'], str(account))
            self.assertEqual(call['config'], config)
            self.assertEqual(args[args.index('-s') + 1], 'workspace-write')
            self.assertIn('approval_policy="never"', args)
            for forbidden in ('--ignore-user-config', '--ignore-rules', '--sandbox', 'project_doc_max_bytes=0'):
                self.assertNotIn(forbidden, args)
            self.assertIn(APPROVAL_RULE, args[-1])
        self.assertIn('resume', self.codex_calls(aid)[-1]['argv'])
        self.h.edit_agent({'id': aid, 'private_pip': True})
        self.done(self.send('agent:' + aid, 'private')['job_id'])
        private = self.codex_calls(aid)[-1]
        self.assertEqual(private['codex_home'], str(self.h.data / 'codex-home-v3'))
        self.assertIn('--ignore-user-config', private['argv'])
        self.assertNotIn('resume', private['argv'])
        self.h.edit_agent({'id': aid, 'private_pip': False})
        self.done(self.send('agent:' + aid, 'normal again')['job_id'])
        self.assertEqual(self.codex_calls(aid)[-1]['codex_home'], str(account))
        self.assertEqual((account / 'config.toml').read_text(), config)

    def test_claude_private_and_draft_only_restore_restrictions(self):
        self.h.edit_agent({'id': self.aid, 'private_pip': True})
        self.done(self.send(text='private')['job_id'])
        args = self.calls()[-1]['argv']
        self.assertIn('--safe-mode', args)
        self.assertNotIn('--chrome', args)
        self.assertNotIn('@' + str(self.h.agents_dir / 'BOTS.md'), args[args.index('--append-system-prompt') + 1])
        self.h.edit_agent({'id': self.aid, 'private_pip': False, 'draft_only': True})
        self.done(self.send(text='draft')['job_id'])
        args = self.calls()[-1]['argv']
        self.assertEqual(args[args.index('--permission-mode') + 1], 'plan')
        self.assertEqual(args[args.index('--tools') + 1], 'Read,Glob,Grep')
        self.assertIn('--strict-mcp-config', args)
        self.assertNotIn('--chrome', args)

    def test_private_creation_has_no_shared_import_and_full_switch_restores_it(self):
        created = self.h.create_agent({'name': 'Clean', 'role': 'Answer.', 'private_pip': True})['agent']
        path = Path(self.h.agents()['clean']['path']) / 'CLAUDE.md'
        link = '@' + str(self.h.agents_dir / 'BOTS.md')
        self.assertNotIn(link, path.read_text())
        self.assertTrue(created['private_pip'])
        self.h.edit_agent({'id': 'clean', 'private_pip': False})
        self.assertIn(link, path.read_text())
        self.h.edit_agent({'id': 'clean', 'private_pip': True})
        self.assertNotIn(link, path.read_text())

    def test_codex_draft_only_is_read_only_and_cannot_resume_full_session(self):
        self.h.config['codex_bin'] = str(FAKE_CODEX)
        aid = self.h.create_agent({'name': 'Draft Coder', 'role': 'Plan.', 'engine': 'codex', 'draft_only': True})['agent']['id']
        for text in ('one', 'two'): self.done(self.send('agent:' + aid, text)['job_id'])
        for call in self.codex_calls(aid):
            self.assertIn('--ignore-user-config', call['argv'])
            self.assertEqual(call['argv'][call['argv'].index('-s') + 1], 'read-only')
            self.assertNotIn('resume', call['argv'])

    def test_linked_switches_live_in_database_and_survive_restart(self):
        folder = self.root / 'linked' / 'Writer'
        folder.mkdir(parents=True)
        (folder / 'AGENTS.md').write_text('Write clearly.')
        self.h.config['external_agent_dirs'] = [str(folder.parent)]
        agent = next(a for a in self.h.agents().values() if a.get('linked'))
        aid = agent['id']
        before = {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob('*') if p.is_file()}
        self.cookie = self.login()
        status, _, body = self.api('/api/agents/' + aid, 'PATCH', {'private_pip': True, 'draft_only': True})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)['agent']['private_pip'])
        self.assertTrue(self.h.agents()[aid]['draft_only'])
        self.assertEqual(before, {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob('*') if p.is_file()})
        settings = self.h._setting('pip_access:' + aid)
        self.assertEqual(settings, {'private_pip': True, 'draft_only': True})
        self.h.close()
        self.h = hub.Hub(self.root, dict(self.h.config), defer_token=True)
        self.addCleanup(self.h.close)
        self.assertTrue(self.h.agents()[aid]['private_pip'])
        self.assertTrue(self.h.agents()[aid]['draft_only'])
        self.assertEqual(before, {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob('*') if p.is_file()})

    def test_switch_validates_boolean_and_requires_auth_and_csrf(self):
        self.assertEqual(self.api('/api/agents/assistant', 'PATCH', {'private_pip': True})[0], 401)
        self.cookie = self.login()
        for value in (None, 0, 'false'):
            self.assertEqual(self.api('/api/agents/assistant', 'PATCH', {'private_pip': value})[0], 400)
        self.assertEqual(self.api('/api/agents/assistant', 'PATCH', {'private_pip': True}, headers={'X-Hub-Request': '0'})[0], 403)
        self.assertEqual(self.api('/api/agents/assistant', 'PATCH', {'private_pip': True})[0], 200)
