"""Offline interaction regressions and stream geometry contracts."""
from pathlib import Path
import shutil
import subprocess
import unittest

from test_chat_presentation import declarations

ROOT = Path(__file__).resolve().parents[1]


class MessagingUI(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is needed for DOM regressions')
    def test_enter_queue_live_ordering_and_polish(self):
        result = subprocess.run(['node', 'tests/messaging_queue_smoke.js'], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Messaging queue smoke checks passed', result.stdout)

    def test_stream_completion_has_no_entry_transform_or_width_change(self):
        self.assertEqual(declarations('.message.stream-final')['animation'], 'none')
        css = (ROOT / 'static/style.css').read_text()
        self.assertNotIn('.message.assistant:not(.streaming-message)', css)
        self.assertEqual(declarations('.message.assistant>.message-content')['width'], 'min(100%,768px)')

    def test_stop_is_an_explicit_non_submit_button(self):
        html = (ROOT / 'static/index.html').read_text()
        self.assertRegex(html, r'id="stopButton"[^>]*type="button"')
        self.assertRegex(html, r'id="sendButton"[^>]*type="submit"')


if __name__ == '__main__':
    unittest.main()
