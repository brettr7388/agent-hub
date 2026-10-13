"""Dependency-free browser flow contract for consent and agent selection."""
from pathlib import Path
import shutil
import subprocess
import unittest


class OnboardingUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Optional Node verifier unavailable')
    def test_consent_preview_and_selection(self):
        root = Path(__file__).resolve().parents[1]
        for command in (['--check', 'static/onboarding.js'], ['tests/onboarding_smoke.js']):
            result = subprocess.run(['node'] + command, cwd=root, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

