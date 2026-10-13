"""UI regressions run the production JS with a local DOM/API fixture."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node is required for DOM regression checks')
class UIPolish(unittest.TestCase):
    def test_chat_ui_polish(self):
        result = subprocess.run(['node', 'tests/ui_polish_smoke.js'], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fraction_square_root_and_safe_fallback(self):
        result = subprocess.run(['node', 'tests/math_smoke.js'], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_version_buttons_sidebar_and_rename(self):
        result = subprocess.run(['node', 'tests/versions_smoke.js'], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
