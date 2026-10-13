"""Offline styling/motion contracts and plain-DOM interaction checks."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / 'static/style.css').read_text()


def block(source, selector):
    start = source.index(selector) + len(selector)
    assert source[start] == '{'
    depth = 1
    end = start + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start + 1:end - 1]


class PolishTests(unittest.TestCase):
    def test_star_mouse_states_are_bare_and_keyboard_focus_is_visible(self):
        bare = block(CSS, '.pin-button,.pin-button:hover,.pin-button:active,.pin-button:focus,.pin-button.pinned')
        for declaration in ('background:transparent', 'border:0', 'box-shadow:none',
                            'outline:none', 'color:var(--muted)',
                            '-webkit-tap-highlight-color:transparent'):
            self.assertIn(declaration, bare)
        self.assertIn('outline:2px solid #4988dc', block(CSS, '.pin-button:focus-visible'))
        self.assertIn('fill:none;stroke:var(--muted)', block(CSS, '.pin-button .icon'))
        self.assertIn('fill:#FFC83D;stroke:#D9A323', block(CSS, '.pin-button.pinned .icon,.nav-pin'))
        self.assertNotRegex(CSS, r'\.pin-button[^{}]*\{[^{}]*(?:background:var|box-shadow:0|border:1px)')

    def test_motion_is_short_and_changes_only_opacity_or_transform(self):
        for name in re.findall(r'@keyframes ([\w-]+)', CSS):
            frames = block(CSS, '@keyframes ' + name)
            properties = re.findall(r'([\w-]+):', frames)
            self.assertTrue(set(properties) <= {'transform', 'opacity'}, (name, properties))
        for selector, body in re.findall(r'([^{}]+)\{([^{}]+)\}', CSS):
            for motion in re.findall(r'(?:animation|transition):([^;}]+)', body):
                if 'infinite' in motion:
                    self.assertIn(selector.strip(), ('.status-spinner', '.typing-bubble span',
                        '.sidebar .avatar[data-state=working]::after,.sidebar .avatar[data-state=thinking]::after,.sidebar .avatar[data-state=waiting]::after'))
                    continue
                durations = re.findall(r'([.\d]+)(ms|s)\b', motion)
                for duration, unit in durations:
                    self.assertLessEqual(float(duration) * (1000 if unit == 's' else 1), 220)
                if durations:
                    self.assertIn('ease-out', motion)
                self.assertNotRegex(motion, r'\b(?:height|width|grid-template-columns)\b')
        self.assertIn('50%{transform:scale(1.25)}', block(CSS, '@keyframes star-pop'))
        self.assertIn('transform:translateY(6px)', block(CSS, '@keyframes card-appear'))
        self.assertEqual(block(CSS, '@keyframes nav-row-added'), 'from{opacity:0}to{opacity:1}')
        self.assertIn('transform:scale(.94)', block(CSS, '.send-button:active'))
        self.assertIn('background-color .12s ease-out', block(CSS, '.sidebar .nav-item,.sidebar .show-all-row,.sidebar .conversation-link,.sidebar .conversation-new,.sidebar .conversation-more'))

    def test_reduced_motion_disables_animation_transition_and_send_press(self):
        reduced = block(CSS, '@media(prefers-reduced-motion:reduce)')
        self.assertIn('*,*::before,*::after', reduced)
        for declaration in ('animation:none!important', 'transition:none!important',
                            'scroll-behavior:auto!important'):
            self.assertIn(declaration, reduced)
        self.assertIn('@media(prefers-reduced-motion:reduce){.send-button:active{transform:none}}', CSS)

    def test_psl_attribution_preserves_original_license(self):
        note = (ROOT / 'docs/licenses/Public-Suffix-List.md').read_text()
        for text in ('Mozilla', 'contributors', 'MPL-2.0', 'https://mozilla.org/MPL/2.0/',
                     'https://publicsuffix.org/list/public_suffix_list.dat'):
            self.assertIn(text, note)
        self.assertIn('docs/licenses/Public-Suffix-List.md', (ROOT / 'README.md').read_text())
        self.assertIn('Mozilla Public\n// License, v. 2.0.', (ROOT / 'docs/public-suffix-list.dat').read_text())

    @unittest.skipUnless(shutil.which('node'), 'Optional Node verifier is not installed')
    def test_polish_interactions(self):
        result = subprocess.run(['node', 'tests/polish_smoke.js'], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Polish smoke checks passed', result.stdout)
