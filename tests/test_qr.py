"""QR fixture and optional browser-encoder parity checks."""

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hub_qr  # noqa: E402


class QRTest(unittest.TestCase):
    def test_known_phone_link(self):
        matrix = hub_qr.encode('https://example.tail123.ts.net/')
        self.assertEqual(len(matrix), 29)
        packed = ''.join('1' if cell else '0' for row in matrix for cell in row).encode()
        self.assertEqual(hashlib.sha256(packed).hexdigest(),
                         'ee187fd8a5042f06035d4027bef909df422abbacdd6d70047b0d81cb69dccd60')

    def test_bounds_and_terminal_quiet_zone(self):
        with self.assertRaises(ValueError):
            hub_qr.encode('x' * 1200)
        matrix = hub_qr.encode('https://example.tail123.ts.net/')
        lines = hub_qr.terminal_qr('https://example.tail123.ts.net/').splitlines()
        self.assertEqual(len(lines), len(matrix) + 8)
        for line in lines:
            self.assertEqual(len(re.sub(r'\x1b\[[0-9;]*m', '', line)), (len(matrix) + 8) * 2)
            self.assertTrue(line.endswith('\x1b[0m'))
        self.assertNotIn('\x1b[40m', '\n'.join(lines[:4] + lines[-4:]))

    @unittest.skipUnless(shutil.which('node'), 'Node is optional')
    def test_browser_encoder_parity(self):
        samples = ['', 'Phone ☎', 'https://example.tail123.ts.net/'] + ['a' * n for n in
                   (15, 27, 43, 63, 85, 107, 123, 153, 181, 210)]
        script = "require('./static/qr.js'); console.log(JSON.stringify(JSON.parse(process.argv[1]).map(s => HubQR.encode(s))))"
        result = subprocess.run(['node', '-e', script, json.dumps(samples)], cwd=ROOT,
                                capture_output=True, text=True, check=True)
        browser = json.loads(result.stdout)
        for sample, expected in zip(samples, browser):
            with self.subTest(length=len(sample)):
                self.assertEqual(hub_qr.encode(sample), expected)


if __name__ == '__main__':
    unittest.main()
