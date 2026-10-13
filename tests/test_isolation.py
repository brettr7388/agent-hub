"""Instruction-boundary regressions. Only deterministic fake CLIs run."""
import json
import os
import subprocess
import unittest
from unittest import mock
import hub
import test_hub
from test_engines import FAKE_CODEX
from hub_isolation import CODEX_CONFIG


class IsolationCase(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    send = test_hub.HubCase.send
    done = test_hub.HubCase.done
    calls = test_hub.HubCase.calls

    def test_claude_safe_mode_explicit_role_notes_and_stale_session(self):
        notes = self.root / 'agents' / 'assistant' / 'NOTES.md'
        notes.write_text('Remember the blue project.')
        self.done(self.send(text='hello')['job_id'])
        args = self.calls()[0]['argv']
        self.assertIn('--safe-mode', args)
        prompt = args[args.index('--append-system-prompt') + 1]
        self.assertIn('Remember the blue project.', prompt)
        self.assertIn('Help with practical answers', prompt)
        with self.h.lock:
            self.h.db.execute("UPDATE sessions SET rules_policy='' WHERE agent_id='assistant'")
            self.h.db.commit()
        self.done(self.send(text='fresh')['job_id'])
        self.assertNotIn('--resume', self.calls()[-1]['argv'])

    def test_codex_isolates_first_and_resumed_turn(self):
        source = self.root / 'source-codex-home'
        source.mkdir()
        (source / 'auth.json').write_text('{"fake": true}')
        (source / 'AGENTS.md').write_text('GLOBAL SENTINEL')
        (source / 'config.toml').write_text('model = "bad"\n')
        self.h.config['codex_bin'] = str(FAKE_CODEX)
        self.h.create_agent({'name': 'Isolated', 'role': 'Write code.', 'engine': 'codex'})
        with mock.patch.dict(os.environ, {'CODEX_HOME': str(source)}):
            for text in ('one', 'two'):
                self.done(self.send('agent:isolated', text)['job_id'])
        path = self.root / 'agents' / 'isolated' / 'fake_codex_calls.jsonl'
        calls = [json.loads(line) for line in path.read_text().splitlines()]
        isolated_home = self.root / 'data' / 'codex-home-v3'
        self.assertEqual((isolated_home / 'auth.json').resolve(), (source / 'auth.json').resolve())
        # macOS may create Library caches when launching Python with a private HOME.
        self.assertEqual({p.name for p in isolated_home.iterdir()} - {'Library'}, {'auth.json', 'config.toml'})
        self.assertNotIn('GLOBAL SENTINEL', (isolated_home / 'config.toml').read_text())
        config = (isolated_home / 'config.toml').read_text()
        for setting in ('skip_host_skill_discovery = true', '[skills.bundled]\nenabled = false',
                        '[skills]\ninclude_instructions = false', 'skill_search = false'):
            self.assertIn(setting, config)
        self.assertEqual(len(calls), 2)
        for call in calls:
            args = call['argv']
            self.assertEqual(call['codex_home'], str(isolated_home))
            self.assertEqual(call['home'], str(isolated_home))
            self.assertEqual(call['cwd'], str(self.root / 'agents' / 'isolated'))
            for flag in ('--ignore-user-config', '--ignore-rules', 'project_doc_max_bytes=0', 'developer_instructions=""',
                         'features.skip_host_skill_discovery=true', 'skills.bundled.enabled=false',
                         'skills.include_instructions=false', 'features.skill_search=false'):
                self.assertIn(flag, args)
        self.assertIn('resume', calls[1]['argv'])

    def test_rules_toggle_invalidates_session_and_explicit_opt_in(self):
        self.done(self.send(text='one')['job_id'])
        self.h.update_agent_rules({'id': 'assistant', 'use_global_rules': True})
        self.assertFalse(self.h.db.execute('SELECT 1 FROM sessions').fetchone())
        self.done(self.send(text='two')['job_id'])
        self.assertNotIn('--safe-mode', self.calls()[-1]['argv'])
        self.assertNotIn('--resume', self.calls()[-1]['argv'])
        self.assertTrue(self.h.agents()['assistant']['use_global_rules'])

    def test_codex_mutated_config_is_restored_for_new_and_resumed_turns(self):
        self.h.config['codex_bin'] = str(FAKE_CODEX)
        self.h.create_agent({'name': 'Mutator', 'role': 'Answer briefly.', 'engine': 'codex'})
        folder = self.root / 'agents' / 'mutator'
        mutation = CODEX_CONFIG.replace('include_instructions = false', 'include_instructions = true') + (
            '\n[projects.fake]\ntrust_level = "trusted"\n[notice]\nmodel_migration_ack = true\n'
            'private_token = "DO-NOT-LOG-THIS"\n')
        (folder / 'fake_codex_responses.json').write_text(json.dumps([
            {'result': 'pong', 'thread_id': 'mutated-session', 'mutate_config': mutation},
            {'result': 'pong', 'thread_id': 'mutated-session', 'mutate_config': mutation},
            {'result': 'pong'},
        ]))
        cid = 'agent:mutator'
        first = self.send(cid, 'one')['job_id']
        self.done(first)
        with self.assertLogs('hub_isolation', level='WARNING') as logs:
            second = self.send(cid, 'two')['job_id']
            self.done(second)
        audit = '\n'.join(logs.output)
        self.assertIn('trust_level', audit)
        self.assertIn('include_instructions', audit)
        self.assertNotIn('DO-NOT-LOG-THIS', audit)
        # A new session must get the same restoration, not only resume.
        with self.h.lock:
            self.h.db.execute('DELETE FROM sessions WHERE agent_id=?', ('mutator',))
            self.h.db.commit()
        with self.assertLogs('hub_isolation', level='WARNING'):
            third = self.send(cid, 'three')['job_id']
            self.done(third)
        calls = [json.loads(line) for line in (folder / 'fake_codex_calls.jsonl').read_text().splitlines()]
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertEqual(call['config'], CODEX_CONFIG)
        self.assertIn('resume', calls[1]['argv'])
        self.assertIn('mutated-session', calls[1]['argv'])
        self.assertNotIn('resume', calls[2]['argv'])
        for jid in (first, second, third):
            self.assertEqual(self.h.db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()[0], 'done')
        self.assertEqual((self.root / 'data' / 'codex-home-v3' / 'config.toml').stat().st_mode & 0o777, 0o600)

    def test_unsupported_cli_fails_closed(self):
        result = subprocess.CompletedProcess([], 0, 'older help', '')
        with mock.patch('hub_isolation.run_bounded', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'cannot isolate rules'):
                self.h.isolation_flags('claude', 'old-fake')

    def test_missing_engine_and_login_explain_the_fix(self):
        with mock.patch('hub_isolation.shutil.which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'install the CLI'):
                self.h.require_engine('codex', 'missing-fake')
        self.h.engine_auth = {'claude': 'login_required'}
        with mock.patch('hub_isolation.shutil.which', return_value='fake'):
            with self.assertRaisesRegex(RuntimeError, 'run: claude'):
                self.h.require_engine('claude', 'fake')

    def test_codex_account_rejects_injected_instructions_and_missing_auth(self):
        source = self.root / 'temporary-codex-auth'
        source.mkdir()
        with mock.patch.dict(os.environ, {'CODEX_HOME': str(source)}):
            with self.assertRaisesRegex(RuntimeError, 'auth.json is unavailable'):
                self.h.codex_environment()
            (source / 'auth.json').write_text('{"fake": true}')
            self.h.codex_environment()
            account = self.root / 'data' / 'codex-home-v3'
            (account / 'AGENTS.md').write_text('injected')
            with self.assertRaisesRegex(RuntimeError, 'Unexpected instruction source'):
                self.h.codex_environment()

    def test_codex_rejects_skills_even_when_disabled(self):
        self.h.codex_environment()
        account = self.root / 'data' / 'codex-home-v3'
        for name in ('skills', '.agents', '.codex', 'rules', 'mcp', 'memories', 'plugins'):
            with self.subTest(source=name):
                (account / name).mkdir()
                with self.assertRaisesRegex(RuntimeError, 'Unexpected instruction source'):
                    self.h.codex_environment()
                (account / name).rmdir()

    def test_legacy_account_and_sessions_are_not_reused(self):
        legacy = self.root / 'data' / 'codex-home'
        (legacy / 'skills').mkdir(parents=True)
        sentinel = legacy / 'skills' / 'SKILL.md'
        sentinel.write_text('legacy instructions')
        self.h.codex_environment()
        self.assertEqual(sentinel.read_text(), 'legacy instructions')
        self.done(self.send(text='hello')['job_id'])
        with self.h.lock:
            self.h.db.execute("UPDATE sessions SET rules_policy='isolated-v2' WHERE agent_id='assistant'")
            self.h.db.commit()
        self.done(self.send(text='fresh')['job_id'])
        self.assertNotIn('--resume', self.calls()[-1]['argv'])

    def test_codex_requires_skill_discovery_control_and_resume_flags(self):
        help_text = '--ignore-user-config --ignore-rules'
        for resume_text, features_text in ((help_text, 'plugins stable true'),
                                           ('old resume help', 'skip_host_skill_discovery under development false')):
            with self.subTest(resume=resume_text, features=features_text):
                self.h._isolation_help = {}
                results = [subprocess.CompletedProcess([], 0, text, '')
                           for text in (help_text, resume_text, features_text)]
                with mock.patch('hub_isolation.run_bounded', side_effect=results):
                    with self.assertRaisesRegex(RuntimeError, 'cannot isolate rules'):
                        self.h.isolation_flags('codex', 'old-fake')

    def test_acknowledgement_is_only_set_after_execution_starts(self):
        self.h.enqueue = lambda aid, jid: None
        sent = self.send(text='ack me')
        history = self.h.history(self.cid)['messages']
        self.assertFalse(history[-1]['acknowledged'])
        self.h.status(sent['job_id'], 'working')
        self.assertTrue(self.h.history(self.cid)['messages'][-1]['acknowledged'])

    def test_rules_reject_busy_agent_and_bad_boolean(self):
        for value in ('false', 0, None):
            with self.assertRaises(hub.HubError):
                self.h.update_agent_rules({'id': 'assistant', 'use_global_rules': value})
        with self.h.lock:
            self.h.db.execute("INSERT INTO jobs(chat_id,agent_id,status) VALUES(?,?,'working')", (self.cid, self.aid))
            self.h.db.commit()
        with self.assertRaises(hub.HubError):
            self.h.update_agent_rules({'id': 'assistant', 'use_global_rules': True})


if __name__ == '__main__': unittest.main()
