"""Offline typography and layout contracts; fake DOM behavior runs in Node."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / 'static/style.css').read_text()
LANE = CSS.split('/* Empty chats, sidebar avatars, and native typography (scoped worktree lane). */')[1]


def declarations(selector, css=CSS):
    """Read repeated exact selectors in source order, including grouped selectors."""
    result = {}
    for selectors, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        # Strip the comment preceding a selector, but keep quoted values intact.
        selectors = re.sub(r'/\*.*?\*/', '', selectors, flags=re.S).strip()
        if selector in [part.strip() for part in selectors.split(',')]:
            for key, value in re.findall(r'([\w-]+)\s*:\s*([^;]+)', body):
                result[key] = value.strip()
    return result


class ChatPresentationTests(unittest.TestCase):
    def test_native_fonts_and_message_text_override_mobile_defaults(self):
        font = declarations(':root')['--font']
        self.assertTrue(font.startswith('-apple-system,"SF Pro Text"'))
        for name in ('"Segoe UI Variable"', '"Segoe UI"', 'Roboto', 'system-ui'):
            self.assertLess(font.index(name), font.index('Inter'), font)
        self.assertNotRegex(CSS, r'\b(?:cv11|ss01|ss03)\b')
        self.assertEqual(declarations('body')['font-feature-settings'], 'normal')
        self.assertEqual(declarations('body')['letter-spacing'], 'normal')
        self.assertEqual(declarations(':root')['--text'], '#1f1f1f')
        self.assertEqual(declarations(':root[data-theme=dark]')['--text'], '#e8e8e8')
        for selector in ('.message-body', '.message.user .message-body'):
            text = declarations(selector)
            self.assertEqual(text['font-size'], '16px')
            self.assertEqual(text['line-height'], '1.65')
        self.assertEqual(declarations('.empty-chat h2')['letter-spacing'], 'normal')
        self.assertEqual(declarations('b')['font-weight'], '600')
        self.assertEqual(declarations('h2')['font-weight'], '600')
        self.assertEqual(declarations('code')['font-family'], 'var(--mono)')
        self.assertEqual(declarations('.markdown code')['font'], '400 var(--fs-meta)/1.5 var(--mono)')

    def test_centering_does_not_depend_on_visible_suggestion_chips(self):
        layout = declarations('.conversation.is-empty', LANE)
        self.assertEqual(layout['display'], 'grid')
        self.assertEqual(layout['grid-template-columns'], 'minmax(0,1fr)', 'composer retains its full reading-column width')
        # Equal spaces above/below the three content rows also center non-Guide chats.
        self.assertEqual(layout['grid-template-rows'], 'auto minmax(20px,1fr) auto auto auto minmax(20px,1fr)')
        self.assertEqual(layout['overflow-y'], 'auto', 'short keyboard viewports can scroll')
        for selector, row in (('.chat-header', '1'), ('.empty-chat', '3'), ('.composer', '4'), ('.suggestion-chips', '5')):
            self.assertEqual(declarations('.conversation.is-empty ' + selector, LANE)['grid-row'], row)
        for selector in ('.empty-chat', '.composer'):
            self.assertEqual(declarations('.conversation.is-empty ' + selector, LANE)['margin'], '0 auto')
        self.assertEqual(declarations('.empty-mark')['width'], '72px')
        self.assertEqual(declarations('.empty-mark .empty-avatar')['height'], '72px')

    def test_sidebar_keeps_single_rows_and_unclipped_status_rings(self):
        for selector in ('.sidebar .nav-wrap', '.sidebar .nav-wrap .nav-item'):
            self.assertEqual(declarations(selector)['height'], '48px')
        self.assertEqual(declarations('.sidebar .nav-name')['font-size'], '15px')
        self.assertEqual(declarations('.sidebar .nav-copy')['display'], 'flex')
        for selector in ('.sidebar .nav-item .avatar', '.app.sidebar-collapsed .nav-item .avatar'):
            face = declarations(selector)
            self.assertEqual(face['width'], '36px')
            self.assertEqual(face['height'], '36px')
            self.assertEqual(face['overflow'], 'visible')
        self.assertEqual(declarations('.nav-linked .icon')['width'], '14px')
        self.assertIn('animation:sidebar-pip-ring 1.1s linear infinite', LANE)
        self.assertIn('inset:-3px', LANE)
        self.assertIn('@media(prefers-reduced-motion:reduce)', LANE)
        app = (ROOT / 'static/app.js').read_text()
        self.assertIn("navRow, kind + '-preview', 48)", app, 'virtual row geometry matches sidebar CSS')

    @unittest.skipUnless(shutil.which('node'), 'Node is optional; no runtime dependency')
    def test_empty_chat_identity_and_first_send_behavior(self):
        result = subprocess.run(['node', 'tests/chat_presentation_smoke.js'], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Chat presentation smoke checks passed', result.stdout)
