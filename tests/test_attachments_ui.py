"""Attachment UI contract and event/DOM regressions; no browser or network."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AttachmentUITests(unittest.TestCase):
    def test_picker_preview_and_authenticated_urls(self):
        html = (ROOT / 'static/index.html').read_text()
        css = (ROOT / 'static/style.css').read_text()
        app = (ROOT / 'static/app.js').read_text()
        picker = re.search(r'<input id="fileInput"[^>]+>', html).group()
        self.assertIn('accept="image/*,', picker)
        self.assertIn('.pdf', picker)
        self.assertIn('multiple', picker)
        self.assertNotIn('capture=', picker, 'picker offers existing photos as well as camera')
        self.assertIn('Drop to attach', html)
        self.assertIn('id="imageLightbox"', html)
        self.assertRegex(css, r'\.upload-thumbnail\{[^}]*width:112px;height:72px')
        self.assertIn('.attachment-list{display:grid;', css)
        self.assertIn('.message.user:has(.attachment-list) .message-content{width:420px}', css)
        self.assertIn('pointer-events:none', css.split('.drop-overlay{')[1].split('}')[0])
        self.assertIn("new URL(url).pathname === '/api/file'", app)
        media = app.split('  function media(attachment) {')[1].split('  function attachmentUrl')[0]
        self.assertNotIn("target = '_blank'", media)
        self.assertIn("img-src 'self' blob:;", html)

    def test_screenshot_instructions_and_private_cache(self):
        readme = (ROOT / 'README.md').read_text()
        self.assertIn('Paste a screenshot with Cmd+V', readme)
        self.assertIn('--add-dir', readme)
        self.assertIn('--image', readme)
        sw = (ROOT / 'static/sw.js').read_text()
        self.assertRegex(sw, r"const SHELL_CACHE = 'agent-hub-shell-v\d+';")
        self.assertNotIn('/api/file', sw)
        self.assertIn('url.search || !SHELL.includes(url.pathname)', sw)

    @unittest.skipUnless(shutil.which('node'), 'Node is optional; no runtime dependency')
    def test_paste_drop_chips_inline_lightbox_and_cleanup(self):
        result = subprocess.run(['node', 'tests/attachments_smoke.js'], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Attachment paste/drop/preview/lightbox smoke checks passed', result.stdout)
