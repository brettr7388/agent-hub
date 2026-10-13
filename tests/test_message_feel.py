"""Guard the browser-dialog boundary and run delayed-network DOM regressions."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MessageFeelTests(unittest.TestCase):
    def test_static_has_no_native_browser_dialog_calls(self):
        forbidden = re.compile(r'\b(?:confirm|alert|prompt)\s*\(')
        for file in sorted((ROOT / 'static').rglob('*.js')):
            with self.subTest(file=file.name):
                self.assertIsNone(forbidden.search(file.read_text()), 'Use app-owned actions, never native browser dialogs')

    @unittest.skipUnless(shutil.which('node'), 'Node is needed for the DOM smoke checks')
    def test_optimistic_reconciliation_retry_and_app_actions(self):
        result = subprocess.run(['node', 'tests/message_feel_smoke.js'], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Message feel smoke checks passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
