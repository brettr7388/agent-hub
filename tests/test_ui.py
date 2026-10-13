"""Static wiring and dependency-free JS checks; layout has a separate browser checklist."""
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.labels = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs: self.ids.append(attrs['id'])
        if tag == 'label' and 'for' in attrs: self.labels.append(attrs['for'])


class UIContractTests(unittest.TestCase):
    def test_all_literal_controls_and_labels_resolve(self):
        parsed = Elements()
        parsed.feed((ROOT / 'static/index.html').read_text())
        self.assertEqual(len(parsed.ids), len(set(parsed.ids)), 'Duplicate HTML ids')
        script = (ROOT / 'static/app.js').read_text()
        refs = set(re.findall(r"\$\(['\"]([\w-]+)['\"]\)", script))
        self.assertFalse(refs - set(parsed.ids), 'JS control without matching HTML id')
        self.assertFalse(set(parsed.labels) - set(parsed.ids), 'Label without matching input')

    def test_single_new_chat_menu_and_team_task_entry_points(self):
        html = (ROOT / 'static/index.html').read_text()
        for control in ('newChatButton', 'newChatMenu', 'pickAgentButton', 'newAgentButton', 'newGroupButton', 'settingsButton', 'workersButton', 'approvalsButton'):
            self.assertIn(f'id="{control}"', html)
        for retired in ('swarmButton', 'headerHelpButton', 'themeButton', 'emptyTour', 'quickStart'):
            self.assertNotIn(f'id="{retired}"', html)
        sidebar = html.split('<section id="conversation"', 1)[0]
        self.assertNotIn('Team task', sidebar)
        self.assertIn('Chat with a Pip', sidebar)
        self.assertIn('New Pip', sidebar)
        self.assertIn('New group', sidebar)
        self.assertIn('id="chatManageButton"', html)
        self.assertIn('id="attachButton"', html)
        self.assertIn('id="teamTaskButton"', html)
        self.assertIn('id="settingsTabs"', html)
        self.assertLess(html.index('id="swarmError"'), html.index('for="swarmGoal"'), 'Team error belongs at the top of the dialog')

        script = (ROOT / 'static/app.js').read_text()
        self.assertIn("const team = el('button', 'secondary', 'Run as a team task…')", script,
                      'The chat header menu must expose team tasks')
        self.assertIn("$('swarmGoal').value = ui.message.value", script,
                      'The team task dialog should start with the composer text')
        self.assertIn("setWorkerAgent(row, members[index])", script,
                      'The team task dialog should preselect agents from the open chat')

    def test_inter_neutral_theme_and_static_font_floor(self):
        css = (ROOT / 'static/style.css').read_text()
        self.assertIn("font-family:Inter", css)
        self.assertIn('--font:Inter', css)
        for token in ('--bg:#fff', '--sidebar:#f9f9f9', '--text:#0d0d0d', '--muted:#6b6b6b',
                      '--line:#e5e5e5', '--r-input:10px', '--r-card:14px', '--r-pill:999px'):
            self.assertIn(token, css)
        for token in ('--bg:#212121', '--sidebar:#171717', '--text:#ececec', '--muted:#a0a0a0', '--line:#303030'):
            self.assertIn(token, css)

        sizes = [float(value) for value in re.findall(r'font-size:\s*(\d+(?:\.\d+)?)px', css)]
        sizes += [float(value) for value in re.findall(r'(?<![-\w])font:\s*(?:\d+\s+)?(\d+(?:\.\d+)?)px', css)]
        self.assertTrue(sizes, 'Expected literal CSS font sizes for the static size check')
        self.assertGreaterEqual(min(sizes), 13, f'Literal CSS font size below 13px: {min(sizes)}px')
        tokens = dict(re.findall(r'(--fs-[a-z]+):([0-9.]+)px', css))
        self.assertEqual(tokens, {'--fs-meta': '13', '--fs-label': '14.5', '--fs-body': '16',
                                  '--fs-dialog': '18', '--fs-section': '22', '--fs-greeting': '30'})
        self.assertTrue(all(float(value) >= 13 for value in tokens.values()))
        self.assertNotRegex(css, r'font-size:\s*(?:0|[.0-9]+(?:em|rem|%))(?:[;}])')
        self.assertIn('small{font-size:var(--fs-meta)}', css)
        self.assertIn('b,strong{font-weight:600}', css)

    def test_responsive_layout_contract_without_layout_engine(self):
        # The JS harness uses fake rectangles: assert layout constraints, not rendered pixels.
        css = (ROOT / 'static/style.css').read_text()
        self.assertIn('grid-template-columns:260px minmax(0,1fr)', css)
        self.assertIn('grid-template-columns:64px minmax(0,1fr)', css)
        self.assertIn('@media(min-width:701px)', css)
        self.assertIn('@media(max-width:700px)', css)
        self.assertIn('.message-content{min-width:0;width:min(100%,768px)}', css)
        self.assertIn('.message-body{font-size:17px}', css)
        self.assertIn('.role-row select{width:100%;min-width:0}', css)
        self.assertIn('width:min(560px,calc(100vw - 24px))', css)
        self.assertIn('max-height:40vh', css)
        self.assertIn('max-width:70%', css)
        self.assertIn('env(safe-area-inset-bottom)', css)
        self.assertIn('@media(prefers-reduced-motion:reduce)', css)
        self.assertEqual(css.count('linear-gradient('), 1, 'Only the greeting has a gradient')
        # 360px dialog: 336px outer minus 38px padding/border leaves 298px;
        # six 44px emoji targets + five 3px gaps fit without an overflowing grid.
        self.assertIn('.emoji-row{grid-template-columns:repeat(6,minmax(0,1fr))}', css)
        self.assertLessEqual(6 * 44 + 5 * 3, 360 - 24 - 38)

    def test_pass10_controls_and_touch_layout(self):
        html = (ROOT / 'static/index.html').read_text()
        css = (ROOT / 'static/style.css').read_text()
        script = (ROOT / 'static/app.js').read_text()
        for icon in ('new', 'search', 'settings', 'sidebar', 'plus', 'send', 'stop',
                     'star', 'down', 'back', 'copy', 'reply', 'more', 'close'):
            self.assertIn(f'id="i-{icon}"', html)
        self.assertIn('id="exportEverything"', html)
        self.assertIn('/api/export/chat?chat_id=', script)
        self.assertIn('/api/export/everything', script)
        self.assertIn('touch-action:pan-y', css)
        self.assertIn('.message.user .quote-stack{align-self:stretch;width:100%', css)
        self.assertIn('.sidebar-footer.compact-footer{display:flex', css)
        self.assertIn('has-scrolled-messages', css)
        self.assertIn('status === \'choosing\'', script)

    def test_pass12_phone_directory_and_privacy_contract(self):
        html = (ROOT / 'static/index.html').read_text()
        css = (ROOT / 'static/style.css').read_text()
        script = (ROOT / 'static/app.js').read_text()
        self.assertIn('id="i-react"', html)
        self.assertIn("action('react', 'React'", script)
        self.assertIn('min-height:max-content', css, 'phone quote lines grow with content')
        self.assertIn('.directory-tools #directorySearch{flex:1 0 100%;width:100%}', css)
        self.assertIn('.compose-toolbar{flex-wrap:nowrap', css)
        self.assertIn('.compose-toolbar .send-button{margin-left:auto}', css)
        self.assertIn('id="directoryShowHidden"', html)
        self.assertIn('id="ownerName"', html)
        self.assertNotIn('Create starters', html)
        self.assertIn('font-weight:400', css)
        self.assertNotRegex(html + script, r'/Users/[^/\s"\']+/')
        self.assertNotRegex(html + script, r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b')
        self.assertNotRegex(html + script, r'(?i)\b(?:KEY|TOKEN|SECRET|PASSWORD)\s*=\s*[A-Za-z0-9+/=_-]{16,}')
        self.assertIn('/api/approvals/workspace', script)
        self.assertIn("'agent-hub-theme'", script)

    def test_avatar_csp_and_rendering_are_compatible(self):
        server = (ROOT / 'hub.py').read_text()
        app = (ROOT / 'static/app.js').read_text()
        pips = (ROOT / 'static/pips.js').read_text()
        self.assertIn("img-src 'self'", server)
        self.assertIn('window.Pips.avatarHTML(pipAgent)', app)
        self.assertIn('return pipSVG(pipFor(agent))', pips)
        self.assertNotIn('data:image/svg+xml', app + pips)
        self.assertNotIn("post('/api/agents/pips'", app)


    def test_pass14_connections_and_content_sized_phone_layout(self):
        html = (ROOT / 'static/index.html').read_text()
        css = (ROOT / 'static/style.css').read_text()
        self.assertRegex(html, r'<details class="advanced-connections"><summary>Advanced</summary>.*?id="approvalsApi"')
        self.assertIn("Connect an external approvals queue that speaks the Agent Hub approvals API — most people don't need this", html)
        self.assertIn('placeholder="http://127.0.0.1:PORT"', html)
        self.assertNotIn('4100', html)
        self.assertIn('<h3>Connected apps</h3>', html)
        directory_rule = re.search(r'\.directory-grid-row\{([^}]+)', css).group(1)
        self.assertNotRegex(directory_rule, r'(?<!-)height:')
        self.assertIn('grid-auto-rows:auto', directory_rule)
        self.assertIn('.pip-card>.secondary,.directory-select{min-height:44px;flex-shrink:0}', css)
        self.assertIn('.settings-tabs button{flex:1 0 auto;min-height:44px}', css)
        self.assertIn('flex-wrap:wrap;overflow:visible;flex-shrink:0', css)
        self.assertIn('.markdown-table-scroll{width:100%;max-width:100%;overflow-x:auto', css)

    def test_pass15_phone_layout_and_first_run_contracts(self):
        html = (ROOT / 'static/index.html').read_text()
        css = (ROOT / 'static/style.css').read_text()
        app = (ROOT / 'static/app.js').read_text()
        for name in ('general', 'schedules', 'connections', 'help'):
            self.assertIn(f'id="settings-tab-{name}" role="tab" aria-controls="settings-panel-{name}"', html)
            self.assertIn(f'id="settings-panel-{name}" role="tabpanel" aria-labelledby="settings-tab-{name}"', html)
        self.assertIn('flex-wrap:wrap;overflow:visible;flex-shrink:0', css)
        self.assertIn('min-width:7rem;word-break:normal;overflow-wrap:normal', css)
        self.assertIn('@media(hover:none){\n.message-actions{display:flex;opacity:1}', css)
        self.assertIn('.message-actions button{min-width:44px;min-height:44px}', css)
        self.assertIn('id="i-retry"', html)
        self.assertIn('@media(max-width:600px){#chatSubtitle{display:none}}', css)
        self.assertIn('1. Open Guide · 2. Ask a question', html)
        self.assertRegex(html, r'id="gettingStartedAgent"[^>]*type="button">Open Guide</button>')
        self.assertIn("$('gettingStartedAgent').addEventListener('click', openGettingStartedGuide)", app)
        self.assertIn('>Scan this computer</button>', html)
        self.assertNotIn('Task and process liveness', (ROOT / 'hub.py').read_text())

    @unittest.skipUnless(shutil.which('node'), 'Optional Node verifier is not installed; no runtime dependency')
    def test_javascript_behavior_and_syntax(self):
        for args in (['--check', 'static/app.js'], ['--check', 'static/markdown.js'], ['--check', 'static/emoji.js'], ['--check', 'static/sw.js'], ['tests/ui_smoke.js']):
            result = subprocess.run(['node'] + args, cwd=ROOT, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            if args == ['tests/ui_smoke.js']:
                self.assertIn('UI smoke checks passed', result.stdout, 'JS checks must reach the final assertion')
