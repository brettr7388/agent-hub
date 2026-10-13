"""Checks that the public release defaults stay generic and portable."""
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hub


class PublicReleaseTests(unittest.TestCase):
    def test_example_config_has_unique_neutral_defaults(self):
        pairs = []
        config = json.loads((ROOT / 'config.example.json').read_text(),
                            object_pairs_hook=lambda values: (pairs.extend(k for k, _ in values), dict(values))[1])
        self.assertEqual(len(pairs), len(set(pairs)), 'example config contains duplicate keys')
        self.assertEqual(config['external_routine_glob'], '')
        self.assertEqual(config['external_agent_dirs'], [])
        self.assertEqual(config['approvals_url'], None)
        self.assertEqual(config['bind'], '127.0.0.1')
        self.assertFalse(config['allow_lan_bind'])

    def test_public_docs_have_no_private_patterns(self):
        public_docs = [ROOT / name for name in ('README.md', 'SETUP.md', 'CONTRIBUTING.md', 'SECURITY.md', 'LICENSE')]
        public_docs.extend(path for path in (ROOT / 'docs').glob('*.md'))
        forbidden = re.compile(r'/Users/[^/\s"\']+/|(?i:\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b)|(?i:\b(?:KEY|TOKEN|SECRET|PASSWORD)\s*[=:]\s*[A-Za-z0-9+/=_-]{16,})')
        for path in public_docs:
            text = path.read_text(encoding='utf-8')
            self.assertIsNone(forbidden.search(text), f'private value in {path.relative_to(ROOT)}')
        for removed in ('EVALUATION.md', 'GAPS.md', 'docs/SCREENSHOTS.md', 'tests/ui_checklist.md'):
            self.assertFalse((ROOT / removed).exists(), f'{removed} must not ship')
        for image in ('screenshot-chat.png', 'screenshot-phone.png', 'screenshot-welcome.png',
                      'screenshot-team.png', 'screenshot-new-agent.png', 'screenshot-phone-list.png'):
            self.assertTrue((ROOT / 'docs' / image).is_file())
        self.assertIn('MIT License', (ROOT / 'LICENSE').read_text())
        self.assertIn('Agent Hub contributors', (ROOT / 'LICENSE').read_text())

    def test_private_runtime_paths_are_not_tracked_for_archives(self):
        listed = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, check=True,
                                stdout=subprocess.PIPE).stdout.decode().split('\0')
        paths = [path for path in listed if path]
        private = [path for path in paths if path == '.remember' or path.startswith(('.remember/', 'data/'))
                   or path == 'config.json' or path.startswith('agents/')]
        self.assertEqual(private, [])
        attributes = (ROOT / '.gitattributes').read_text(encoding='utf-8')
        for entry in ('/.remember/** export-ignore', '/data/** export-ignore',
                      '/config.json export-ignore', '/agents/** export-ignore'):
            self.assertIn(entry, attributes)

    def test_windows_fails_with_friendly_message_before_unix_lock_import(self):
        with mock.patch.object(hub.sys, 'platform', 'win32'):
            with self.assertRaises(SystemExit) as caught:
                hub.main()
        self.assertEqual(str(caught.exception), "Windows isn't supported yet; use WSL")


if __name__ == '__main__':
    unittest.main()
