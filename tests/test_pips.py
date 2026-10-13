"""Run the dependency-free Pip renderer smoke check in the main test suite."""
from pathlib import Path
import subprocess
import shutil
import unittest


class PipRenderer(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is optional for JavaScript smoke checks")
    def test_pips_smoke(self):
        script = Path(__file__).with_name('pips_smoke.js')
        result = subprocess.run(
            ['node', str(script)], capture_output=True, text=True,
            timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('pips smoke passed', result.stdout)
