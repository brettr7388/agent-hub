"""Local onboarding uses a fake home and fake CLIs; no real model or network."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
import hub
import test_hub
from hub_onboarding import MAX_SUMMARY, _languages, _safe_file, _strict_suggestions, scan_home


FAKE_CODEX = Path(__file__).with_name('fake_codex.py').resolve()


class OnboardingCase(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    login = test_hub.HubCase.login
    api = test_hub.HubCase.api
    request = test_hub.HubCase.request

    def home(self):
        path = self.root / 'fake-home'
        path.mkdir(exist_ok=True)
        return path

    def test_pass15_scan_label_state_survives_reload_and_skip(self):
        self.assertFalse(self.h.onboarding_status()['scanned'])
        self.h.onboarding_skip({})
        self.assertFalse(self.h.onboarding_status()['scanned'])
        with mock.patch('hub_onboarding.scan_home', return_value=('Safe inventory', {}, 0)):
            self.h.onboarding_preview({'sources': ['claude']})
        self.assertTrue(self.h.onboarding_status()['scanned'])
        self.h.onboarding_skip({})
        config = json.loads((self.root / 'config.json').read_text())
        self.assertTrue(config['onboarding_scanned'])
        self.assertTrue(self.h.onboarding_status()['scanned'])

    def test_api_requires_login(self):
        self.assertEqual(self.request('/api/onboarding')[0], 401)
        self.assertEqual(self.request('/api/onboarding/preview', 'POST', {'sources': ['claude']})[0], 401)
        self.cookie = self.login()
        self.assertEqual(self.api('/api/onboarding')[0], 200)

    def test_scan_excludes_secrets_symlinks_and_caps(self):
        home = self.home()
        agents = home / '.claude' / 'agents'; agents.mkdir(parents=True)
        (agents / 'writer.md').write_text('---\nname: Writer\ndescription: Helps with sk-abcdefgh12345678 and password=hunter2\n---\nSECRET BODY\n')
        (agents / 'credentials.md').write_text('---\nname: SHOULD_NOT_LEAK\n---\n')
        outside = self.root / 'outside.md'; outside.write_text('---\nname: SYMLINK_SECRET\n---\n')
        (agents / 'linked.md').symlink_to(outside)
        skill_outside = self.root / 'outside-skill'; skill_outside.mkdir()
        (skill_outside / 'SKILL.md').write_text('---\nname: ANCESTOR_SYMLINK_SECRET\n---\n')
        skills = home / '.claude' / 'skills'; skills.mkdir()
        (skills / 'linked').symlink_to(skill_outside, target_is_directory=True)
        (home / '.claude' / 'CLAUDE.md').write_text('Rule\nAPI_KEY=abc123\n' + '\n'.join('rule-%s' % i for i in range(38)) + '\nFORTY_ONE_SECRET\n')
        commands = home / '.claude' / 'commands'; commands.mkdir()
        for i in range(80): (commands / (str(i).zfill(3) + '-' + 'a' * 155 + '.md')).write_text('ignored body')
        (home / '.codex').mkdir()
        (home / '.codex' / 'AGENTS.md').write_text('good\nghp_abcdefgh1234567890\n')
        repo = home / 'code' / 'one' / 'two' / 'three'; repo.mkdir(parents=True)
        (repo / '.git').mkdir()
        (repo / '.git' / 'config').write_text('[remote "origin"]\n url = https://user:secret@github.com/acme/one.git?access_token=HIDDEN\n')
        (repo / 'README.md').write_text('Project\nxoxb-abcdefgh12345678\n' + '\n'.join('readme-%s' % i for i in range(13)) + '\nSIXTEEN_SECRET\n')
        deep = repo / 'four'; deep.mkdir(); (deep / '.git').mkdir()
        extra_deep = home / 'code' / 'a' / 'b' / 'c' / 'deep'; extra_deep.mkdir(parents=True); (extra_deep / '.git').mkdir()
        home_deep = home / 'shallow' / 'deeper'; home_deep.mkdir(parents=True); (home_deep / '.git').mkdir()
        summary, folders, findings = scan_home(home, ['claude', 'codex', 'code'], 'gpt-6.1-sol')
        for secret in ('sk-abcdefgh', 'hunter2', 'SHOULD_NOT_LEAK', 'SYMLINK_SECRET', 'ANCESTOR_SYMLINK_SECRET', 'abc123', 'ghp_', 'xoxb-', 'HIDDEN', 'user:secret', 'SECRET BODY', 'FORTY_ONE_SECRET', 'SIXTEEN_SECRET'):
            self.assertNotIn(secret, summary)
        code_summary, code_folders, _ = scan_home(home, ['code'])
        self.assertIn('github.com/acme/one', code_summary)
        self.assertNotIn('xoxb-', code_summary)
        self.assertNotIn('SIXTEEN_SECRET', code_summary)
        self.assertIn('code/one/two/three', code_folders)
        self.assertNotIn('code/one/two/three/four', code_folders)
        self.assertNotIn('code/a/b/c/deep', code_folders)
        self.assertNotIn('shallow/deeper', code_folders)
        for path in commands.iterdir(): path.unlink()
        claude_summary, _, _ = scan_home(home, ['claude'])
        self.assertNotIn('FORTY_ONE_SECRET', claude_summary)
        self.assertLessEqual(len(summary.encode()), MAX_SUMMARY)
        self.assertGreater(findings, 0)
        with mock.patch('hub_onboarding.os.walk', return_value=[(str(repo), [], ['x.py'] * 2000 + ['last.js'])]):
            self.assertEqual(_languages(repo), 'Python')

    def test_zero_findings_starters_create_once_and_skip(self):
        home = self.home()
        with mock.patch.dict(os.environ, {'HOME': str(home)}):
            preview = self.h.onboarding_preview({'sources': ['claude', 'code']})
        self.assertLessEqual(len(preview['summary'].encode()), MAX_SUMMARY)
        found = self.h.onboarding_suggest({'token': preview['token']})
        self.assertTrue(found['starter'])
        self.assertEqual(len(found['suggestions']), 3)
        first = found['suggestions'][0]
        payload = {'token': preview['token'], 'suggestions': [dict(first, original_name=first['name'], selected=True)]}
        payload['suggestions'][0]['name'] = 'My New Assistant'
        made = self.h.onboarding_create(payload)
        self.assertEqual(made['status'], 'done')
        self.assertTrue(self.h.product_state()['getting_started']['completed'])
        self.assertFalse(made['agents'][0]['use_global_rules'])
        self.assertEqual(self.h.onboarding_create(payload), made)
        self.assertEqual(json.loads((self.root / 'config.json').read_text())['onboarding_scan'], 'done')
        self.assertEqual(self.h.onboarding_skip({})['status'], 'done')
        self.assertEqual(json.loads((self.root / 'config.json').read_text())['onboarding_scan'], 'done')

    def test_source_budgets_project_names_large_prefix_and_coding_folder(self):
        home = self.home()
        skills = home / '.claude' / 'skills'; skills.mkdir(parents=True)
        for index in range(75):
            skill = skills / ('skill-%02d' % index); skill.mkdir()
            (skill / 'SKILL.md').write_text('---\nname: skill-%02d\ndescription: %s\n---\n' % (index, 'long detail ' * 100))
        projects = home / '.claude' / 'projects'; projects.mkdir()
        for name in ('sample-hub', 'sample-app', 'sample-hub'):
            (projects / ('-' + '-'.join(home.parts[1:]) + '-' + name)).mkdir(exist_ok=True)
        large = skills / 'last30days'; large.mkdir()
        (large / 'SKILL.md').write_text('---\nname: last30days\ndescription: Timely research\n---\n' + 'x' * 140000)
        self.assertLessEqual(len(_safe_file(large / 'SKILL.md', 8192).encode()), 4096)
        codex = home / '.codex'; codex.mkdir()
        (codex / 'AGENTS.md').write_text('Codex works on code.\n')
        (codex / 'config.toml').write_text('model = "gpt-6.1-sol"\n')
        repos = []
        for name, extension in (('sample-hub', 'py'), ('affiliate', 'js'), ('forge', 'go')):
            repo = home / 'code' / name; repo.mkdir(parents=True)
            (repo / '.git').mkdir(); (repo / ('main.' + extension)).write_text('content')
            repos.append(repo)
        summary, folders, _ = scan_home(home, ['claude', 'codex', 'code'])
        self.assertLessEqual(len(summary.encode()), MAX_SUMMARY)
        self.assertIn('Configured Codex model: gpt-6.1-sol', summary)
        self.assertIn('Code folder: code/sample-hub | Python', summary)
        self.assertIn('Code folder: code/affiliate | JavaScript', summary)
        self.assertIn('Code folder: code/forge | Go', summary)
        self.assertIn('Claude project folder name: sample-hub', summary)
        self.assertEqual(summary.count('Claude project folder name: sample-hub'), 1)
        self.assertIn('(truncated)', summary)
        large_summary, _, _ = scan_home(home, ['claude'])
        self.assertIn('Claude skill: last30days', large_summary)
        self.assertEqual(set(folders), {'code/sample-hub', 'code/affiliate', 'code/forge'})
        rows = [dict(name=name, emoji='🤖', title=name, role=role, engine='claude', model='haiku', project_folder=None, why='Useful')
                for name, role in (('Builder', 'Writes code for code/sample-hub'), ('Researcher', 'Finds sources'), ('Planner', 'Makes plans'))]
        suggestions, _, _ = _strict_suggestions({'suggestions': rows, 'group': None, 'team': None}, folders, 'claude', 'haiku')
        self.assertEqual(suggestions[0]['project_folder'], folders['code/sample-hub'])
        self.assertIsNone(suggestions[1]['project_folder'])

    def test_token_redaction_keeps_normal_words(self):
        home = self.home(); (home / '.claude').mkdir()
        (home / '.claude' / 'CLAUDE.md').write_text('task-relevant desk-work risk-taking ' + 'documentation' * 5 + '\nsk-abcdefgh12345678\n')
        summary, _, _ = scan_home(home, ['claude'])
        self.assertNotIn('task-relevant desk-work risk-taking', summary)
        self.assertNotIn('documentation' * 5, summary)
        self.assertNotIn('sk-abcdefgh12345678', summary)

    def test_large_skill_description_is_read_from_prefix(self):
        home = self.home()
        skill = home / '.claude' / 'skills' / 'large'; skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('---\nname: Large Skill\ndescription: Explains giant files\n---\n' + 'x' * 140000)
        summary, _, _ = scan_home(home, ['claude'])
        self.assertIn('Description for Large Skill: Explains giant files', summary)

    def test_all_forty_long_repositories_keep_full_names_and_languages(self):
        home = self.home()
        (home / '.claude').mkdir(); (home / '.claude' / 'CLAUDE.md').write_text('D' * 10000)
        (home / '.codex').mkdir(); (home / '.codex' / 'AGENTS.md').write_text('E' * 10000)
        (home / '.codex' / 'config.toml').write_text('model = "gpt-6.1-sol"\n')
        names = []
        for index in range(40):
            name = 'project-%02d-' % index + '界' * 37
            repo = home / 'code' / name; repo.mkdir(parents=True)
            (repo / '.git').mkdir(); (repo / 'main.py').write_text('pass')
            names.append('code/' + name)
        summary, folders, _ = scan_home(home, ['claude', 'codex', 'code'])
        self.assertLessEqual(len(summary.encode()), MAX_SUMMARY)
        self.assertEqual(set(folders), set(names))
        for name in names:
            self.assertIn('Code folder: ' + name + ' | Python', summary)
        self.assertIn('Configured Codex model: gpt-6.1-sol', summary)

    def test_repository_choices_match_visible_preview_when_discovery_is_limited(self):
        home = self.home()
        group = home / 'code' / ('group-' + 'a' * 75)
        for index in range(40):
            repo = group / ('project-%02d-' % index + 'b' * 230)
            repo.mkdir(parents=True); (repo / '.git').mkdir(); (repo / 'main.py').write_text('pass')
        summary, folders, _ = scan_home(home, ['code'])
        self.assertLessEqual(len(summary.encode()), MAX_SUMMARY)
        self.assertLess(len(folders), 40)
        self.assertIn('Code discovery limited:', summary)
        for name in folders:
            self.assertIn('Code folder: ' + name + ' | Python', summary)
        self.assertEqual(summary.count('Code folder: '), len(folders))

    def test_cli_json_validation_fallback_and_exact_preview(self):
        home = self.home(); (home / '.claude').mkdir()
        (home / '.claude' / 'CLAUDE.md').write_text('Build useful tools.\npassword=supersecret\n')
        agent = home / '.claude' / 'agents' / 'builder.md'; agent.parent.mkdir()
        agent.write_text('---\nname: Builder\ndescription: Makes useful tools\n---\n')
        self.h.config['codex_bin'] = str(FAKE_CODEX)
        self.h.config['detect_engines'] = False
        rows = [dict(name=n, emoji='🔎', title=n + ' title', role='Assist with ' + n,
                     engine='claude', model='haiku', project_folder=None, why='Found relevant work')
                for n in ('Builder', 'Reviewer', 'Planner')]
        scratch = self.h.data / 'onboarding-run'; scratch.mkdir()
        (scratch / 'fake_responses.json').write_text(json.dumps([{'result': '{bad json'}]))
        (scratch / 'fake_codex_responses.json').write_text(json.dumps([{'result': json.dumps({'suggestions': rows, 'group': {'name': 'Build group', 'agents': ['Builder', 'Reviewer']}, 'team': {'name': 'Review team', 'agents': ['Builder', 'Reviewer']}})}]))
        with mock.patch.dict(os.environ, {'HOME': str(home)}):
            preview = self.h.onboarding_preview({'sources': ['claude']})
            found = self.h.onboarding_suggest({'token': preview['token']})
        self.assertFalse(found['starter'])
        self.assertEqual(len(found['suggestions']), 3)
        self.assertTrue(all(x['selected'] for x in found['suggestions']))
        calls = [json.loads(x) for x in (scratch / 'fake_calls.jsonl').read_text().splitlines()]
        self.assertIn(preview['summary'], calls[0]['argv'][1])
        self.assertNotIn('supersecret', calls[0]['argv'][1])
        self.assertIn('--tools', calls[0]['argv'])
        codex = [json.loads(x) for x in (scratch / 'fake_codex_calls.jsonl').read_text().splitlines()]
        self.assertIn('read-only', codex[0]['argv'])
        self.assertNotEqual(codex[0]['home'], str(home))
        entries = [dict(x, original_name=x['name'], selected=True) for x in found['suggestions'][:2]]
        entries[0]['name'] = 'Renamed Builder'
        entries[1]['name'] = 'New Reviewer'
        made = self.h.onboarding_create({'token': preview['token'], 'suggestions': entries, 'group': {'selected': True}})
        self.assertEqual(len(made['agents']), 2)
        self.assertEqual(set(made['group']['agents']), {a['id'] for a in made['agents']})
        self.assertEqual(made['team']['name'], 'Review team')

    def test_bad_json_without_fallback_is_retryable(self):
        home = self.home(); (home / '.codex').mkdir()
        (home / '.codex' / 'AGENTS.md').write_text('Hello')
        self.h.config['codex_bin'] = '/missing/codex'
        scratch = self.h.data / 'onboarding-run'; scratch.mkdir()
        (scratch / 'fake_responses.json').write_text(json.dumps([{'result': '{bad json'}]))
        with mock.patch.dict(os.environ, {'HOME': str(home)}):
            preview = self.h.onboarding_preview({'sources': ['codex']})
            with self.assertRaises(hub.HubError) as got:
                self.h.onboarding_suggest({'token': preview['token']})
        self.assertEqual(got.exception.status, 502)
        self.assertIsNone(self.h.config.get('onboarding_scan'))

    def test_invalid_emoji_prevents_partial_creation_and_suggestion_is_once(self):
        home = self.home(); (home / '.claude').mkdir()
        (home / '.claude' / 'CLAUDE.md').write_text('Projects')
        agent = home / '.claude' / 'agents' / 'builder.md'; agent.parent.mkdir()
        agent.write_text('---\nname: Builder\n---\n')
        rows = [dict(name=n, emoji='✅', title=n, role='Help with ' + n,
                     engine='claude', model='haiku', project_folder=None, why='Useful')
                for n in ('Alpha', 'Beta', 'Gamma')]
        scratch = self.h.data / 'onboarding-run'; scratch.mkdir()
        (scratch / 'fake_responses.json').write_text(json.dumps([{'result': json.dumps({'suggestions': rows, 'group': None, 'team': None}), 'sleep': .1}]))
        with mock.patch.dict(os.environ, {'HOME': str(home)}):
            preview = self.h.onboarding_preview({'sources': ['claude']})
            answers, errors = [], []
            def call():
                try: answers.append(self.h.onboarding_suggest({'token': preview['token']}))
                except Exception as error: errors.append(error)
            threads = [threading.Thread(target=call) for _ in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
        self.assertFalse(errors)
        self.assertEqual(answers[0], answers[1])
        self.assertEqual(len((scratch / 'fake_calls.jsonl').read_text().splitlines()), 1)
        cards = [dict(x, original_name=x['name'], selected=True) for x in answers[0]['suggestions'][:2]]
        cards[1]['emoji'] = 'not emoji'
        with self.assertRaises(hub.HubError):
            self.h.onboarding_create({'token': preview['token'], 'suggestions': cards})
        self.assertNotIn('alpha', self.h.agents())


if __name__ == '__main__': unittest.main()
