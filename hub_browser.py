"""Dedicated Pip browser, durable owner taps, and vault-only logins."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import tempfile
from urllib.parse import urlsplit

import hub_fs
from hub_cdp import CDPClient, CDPError, FILLED, fill_login, origin_matches
from hub_browser_pipe import PipeBroker, PipeError
from hub_login import LoginError, LoginStore, _host, is_local_host, login_allows_site


BROWSER_PROMPT = '''Browser use: like a normal Claude Code session you may use the owner's everyday Chrome (Claude in Chrome) for
sites the owner is already signed into. Prefer the separate Pip browser (its own persistent profile) for accounts you
sign into on the owner's behalf, when it is available.
If a login is needed, output a standalone fenced agent-hub JSON block:
{"action":"signin_request","site":"tiktok.com","reason":"to read your inbox"}
For an optional saved-login fill, output {"action":"login_fill_request","site":"tiktok.com"} in the same fence.
The owner must tap every fill. The Hub reads the OS vault and fills the verified login fields; you receive only status.
Never ask for, read, print, store or paste passwords; never inspect credential fields, the OS vault, or browser credential files.
For local sites include the development port, for example 127.0.0.1:4841. After Filled, click Sign in without navigating or reloading.
After requesting a sign-in or fill, wait for the owner's response before continuing browser work.
'''


def parse_browser_cards(text):
    """Only standalone, completed fences outside other fences/quotes make controls."""
    if len(text) > 100000: return text, []
    lines = text.splitlines(keepends=True)
    result, cards = [], []
    outer = None
    index = 0
    while index < len(lines):
        line = lines[index]
        marker = re.match(r'^(`{3,}|~{3,})(.*)$', line.rstrip('\r\n'))
        if outer:
            result.append(line)
            if marker and marker[1][0] == outer[0] and len(marker[1]) >= len(outer) and not marker[2].strip(): outer = None
            index += 1; continue
        if not marker or marker[1] != '```' or marker[2].strip().lower() != 'agent-hub':
            if marker: outer = marker[1]
            result.append(line); index += 1; continue
        end = index + 1
        while end < len(lines) and lines[end].rstrip('\r\n') != '```': end += 1
        if end == len(lines): result.extend(lines[index:]); break
        payload = ''.join(lines[index + 1:end])
        try:
            item = json.loads(payload)
            if not isinstance(item, dict) or set(item) - {'action', 'site', 'reason'}: raise ValueError()
            kind = item.get('action')
            if kind not in ('signin_request', 'login_fill_request'): raise ValueError()
            site = _host(item.get('site'))
            reason = item.get('reason', '')
            if not isinstance(reason, str) or len(reason) > 400 or (kind == 'signin_request' and not reason.strip()): raise ValueError()
            cards.append({'kind': kind, 'site': site, 'reason': reason.strip(), 'status': 'pending'})
        except (ValueError, TypeError): result.extend(lines[index:end + 1])
        index = end + 1
    return ''.join(result).strip(), cards


def error(status, message):
    from hub import HubError
    raise HubError(status, message)


def installed_mcp(config):
    """Resolve a local install. Never npx/download or use the auto-connect option."""
    command = config.get('pip_browser_mcp_command')
    args = config.get('pip_browser_mcp_args', [])
    if command:
        if not isinstance(command, str) or not isinstance(args, list) or not all(isinstance(x, str) for x in args): return None
        # Browser-targeting flags are Hub-owned, never inherited from configuration.
        if any(re.search(r'auto.?connect|browser.?url|ws.?endpoint|ws.?headers|user.?data.?dir|chrome.?args|executable.?path|channel|isolated', x, re.I) for x in args): return None
        binary = shutil.which(os.path.expanduser(command))
        if binary: return binary, args
    binary = shutil.which('chrome-devtools-mcp')
    if binary: return binary, []
    node = shutil.which('node')
    if not node: return None
    # npx's existing cache is usable offline; do not invoke npx itself.
    cache = Path.home() / '.npm/_npx'
    candidates = []
    if cache.is_dir():
        for folder in cache.iterdir():
            package = folder / 'node_modules/chrome-devtools-mcp'
            try:
                version = json.loads((package / 'package.json').read_text()).get('version', '0')
                version = tuple(int(part) for part in version.split('.')[:3])
            except (OSError, ValueError, TypeError): continue
            for entry in ('build/src/bin/chrome-devtools-mcp.js', 'build/src/index.js'):
                script = package / entry
                if script.is_file():
                    candidates.append((version, script)); break
    if not candidates: return None
    script = max(candidates, key=lambda p: (p[0], p[1].stat().st_mtime))[1]
    return node, [str(script)]


def pip_mcp_command(mcp, socket_path):
    """Wrap only a local Node MCP entry point; never launch a network installer."""
    command, args = mcp
    node = shutil.which('node')
    if not node: raise CDPError('Install Node to use Pip browser tools.')
    if Path(command).name in ('node', 'nodejs') and args:
        script, extra = args[0], args[1:]
    else:
        script, extra = str(Path(command).resolve()), args
        try:
            with open(script, 'rb') as stream: first = stream.readline(512)
        except OSError: raise CDPError('Pip browser MCP entry point is unavailable.') from None
        if not first.startswith(b'#!') or b'node' not in first:
            raise CDPError('Pip browser requires a locally installed Node Chrome DevTools MCP.')
    if not Path(script).is_file(): raise CDPError('Pip browser MCP entry point is unavailable.')
    return node, [str(Path(__file__).with_name('hub_browser_mcp.mjs')), str(socket_path),
                  str(Path(script).resolve()), *extra, '--no-performance-crux']


class PipBrowser:
    def __init__(self, data, config=None):
        self.data = Path(data)
        self.profile = self.data / 'pip-browser-profile'
        self.config = config or {}
        self.process = None
        self.broker = None
        self.socket_dir = None
        self.login_targets = {}
        self.last_target = None
        self.lock = threading.RLock()

    def _binary(self):
        configured = self.config.get('pip_browser_bin')
        if configured: return shutil.which(os.path.expanduser(configured))
        if sys.platform == 'darwin':
            for path in ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Chromium.app/Contents/MacOS/Chromium'):
                if os.path.isfile(path): return path
        return next((p for p in (shutil.which(x) for x in ('google-chrome', 'chromium', 'chromium-browser')) if p), None)

    def _profile(self, create=False):
        # Pin every directory component. Never accept a configurable profile path.
        fd = hub_fs.open_directory(self.data)
        os.close(fd)
        if create: hub_fs.mkdir(self.profile, mode=0o700, exist_ok=True)
        if self.profile.exists() or self.profile.is_symlink():
            fd = hub_fs.open_directory(self.profile)
            try:
                if os.fstat(fd).st_uid != os.getuid(): raise CDPError('Pip browser profile belongs to another user.')
                os.fchmod(fd, 0o700)
            finally: os.close(fd)
        return self.profile

    def _endpoint(self):
        # Never reconnect to a leftover DevToolsActivePort from an older Hub.
        return (None, self.broker.socket_path) if self.broker and self.broker.running else None

    def status(self):
        with self.lock:
            return {'available': bool(self._binary()), 'running': bool(self._endpoint()),
                    'profile': 'data/pip-browser-profile', 'browser_url': None,
                    'transport': 'private pipe', 'mcp_available': bool(installed_mcp(self.config))}

    def ensure(self):
        with self.lock:
            if self._endpoint(): return self._endpoint()
            if self.broker or self.socket_dir: self.close()
            binary = self._binary()
            if not binary: raise CDPError('Install Chrome to use the Pip browser.')
            profile = self._profile(create=True)
            self._refuse_live_profile()
            # Short paths work on macOS's Unix socket length limit. mkdtemp is
            # owner-only and the socket is 0600; other OS users cannot connect.
            self.socket_dir = tempfile.mkdtemp(prefix='hub-pip-', dir=str(Path('/tmp').resolve()))
            try:
                self.broker = PipeBroker.launch(binary, profile, Path(self.socket_dir) / 'cdp.sock')
                self.process = self.broker.process
                with self.broker.connect() as client: client.call('Browser.getVersion')
                return self._endpoint()
            except (OSError, ValueError, PipeError, EOFError):
                self.close()
                raise CDPError('Pip browser did not start. Close any older Pip browser window and retry.') from None

    def close(self):
        with self.lock:
            if self.broker:
                self.broker.close()
                self.broker = None
            if self.socket_dir:
                try: os.rmdir(self.socket_dir)
                except OSError: pass
                self.socket_dir = None
            self.login_targets.clear()
            self.last_target = None

    def _refuse_live_profile(self):
        try:
            pid = int(os.readlink(self.profile / 'SingletonLock').rsplit('-', 1)[-1])
            if pid <= 0: raise ValueError()
            try: os.kill(pid, 0)
            except ProcessLookupError: return
            raise CDPError('Close the existing Pip browser window before retrying.')
        except FileNotFoundError: pass
        except (OSError, ValueError):
            raise CDPError('Pip browser lock could not be checked; close its window before retrying.') from None

    @staticmethod
    def _site_match(url, site):
        return origin_matches(url, {'site': site, 'subdomains': []})

    def _targets(self, client):
        return [page for page in client.call('Target.getTargets').get('targetInfos', [])
                if page.get('type') == 'page'][:100]

    def _front(self):
        if sys.platform == 'darwin':
            # Only activates the app. All navigation/target access goes to our CDP.
            bundle = 'org.chromium.Chromium' if 'Chromium' in (self._binary() or '') else 'com.google.Chrome'
            try:
                subprocess.run(['osascript', '-e', 'tell application id "' + bundle + '" to activate'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            except (OSError, subprocess.SubprocessError): pass

    def open(self, site=None, requester=None):
        with self.lock:
            site = _host(site) if site else None
            self.ensure()
            self._front()
            try:
                with self.broker.connect() as client:
                    pages = self._targets(client)
                    pinned = self.login_targets.get((requester, site)) if site else self.last_target
                    target = next((page for page in pages if page['targetId'] == pinned and
                                   (not site or self._site_match(page.get('url', ''), site))), None)
                    if not target and site:
                        target = next((page for page in pages if self._site_match(page.get('url', ''), site)), None)
                    if not target and not site and pages: target = pages[0]
                    if not target:
                        url = (('http://' if is_local_host(urlsplit('//' + site).hostname) else 'https://') + site) if site else 'about:blank'
                        target = client.call('Target.createTarget', {'url': url})
                    identifier = target['targetId']
                    client.call('Target.activateTarget', {'targetId': identifier})
                    if site: self.login_targets[(requester, site)] = identifier
                    self.last_target = identifier
            except (PipeError, EOFError): raise CDPError('Pip browser could not open its login tab.') from None
            return dict(self.status(), opened_on='the host computer')

    def fill(self, login, requester=None, site=None):
        with self.lock:
            if not self._endpoint(): return 'Pip browser is closed — refused'
            try:
                with self.broker.connect() as client:
                    pages = self._targets(client)
                    target_site = site or login['site']
                    if not login_allows_site(login, target_site): return 'No saved login for ' + target_site + ' — refused'
                    scope = login if target_site == login['site'] else dict(login, site=target_site, subdomains=[])
                    pinned = self.login_targets.get((requester, target_site))
                    if pinned:
                        page = next((p for p in pages if p['targetId'] == pinned), None)
                        if not page: return 'The Pip login tab was closed — refused; open the sign-in card again'
                        if not origin_matches(page.get('url', ''), scope):
                            return 'The Pip login tab navigated away from ' + login['site'] + ' — refused'
                    else:
                        matching = [p for p in pages if origin_matches(p.get('url', ''), scope)]
                        if not matching: return 'No Pip login tab for ' + login['site'] + ' — refused; open that site in the Pip browser'
                        if len(matching) != 1: return 'Multiple Pip tabs match ' + login['site'] + ' — refused; open the sign-in card to choose its login tab'
                        page = matching[0]
                        self.login_targets[(requester, target_site)] = page['targetId']
                with self.broker.connect(page['targetId']) as client:
                    # Pin the target URL across attach, including redirects to
                    # explicitly allowed saved subdomains that already happened.
                    return fill_login(client, scope, expected_url=page.get('url', ''))
            except (PipeError, EOFError): return 'The Pip login tab changed or closed — refused'

    def reset(self):
        with self.lock:
            self.close()
            self._refuse_live_profile()
            # Descriptor-pinned deletion never follows Chrome's lock symlinks.
            self._profile()
            parent = hub_fs.open_directory(self.data)
            try:
                try: fd = os.open('pip-browser-profile', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                except FileNotFoundError: return self.status()
                try: self._wipe(fd)
                finally: os.close(fd)
                os.rmdir('pip-browser-profile', dir_fd=parent)
            finally: os.close(parent)
            return self.status()

    @staticmethod
    def _wipe(fd):
        import stat
        for name in os.listdir(fd):
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try: PipBrowser._wipe(child)
                finally: os.close(child)
                os.rmdir(name, dir_fd=fd)
            else: os.unlink(name, dir_fd=fd)


class BrowserMixin:
    def pip_browser(self):
        with self.lock:
            if not hasattr(self, '_pip_browser'): self._pip_browser = PipBrowser(self.data, self.config)
            return self._pip_browser

    def login_store(self):
        with self.lock:
            if not hasattr(self, '_login_store'): self._login_store = LoginStore()
            return self._login_store

    def pip_browser_status(self):
        try: result = self.pip_browser().status()
        except (OSError, ValueError): result = {'available': False, 'running': False, 'profile': 'data/pip-browser-profile', 'mcp_available': False}
        return dict(result, saved_logins_available=self.login_store().available)

    def pip_browser_open(self, body):
        try: return dict(self.pip_browser().open(body.get('site')), saved_logins_available=self.login_store().available)
        except (OSError, ValueError, CDPError): error(400, 'Pip browser could not open. Check its status on this computer.')

    def pip_browser_reset(self, body):
        if body.get('confirm') is not True: error(400, 'Confirm clearing the Pip browser profile.')
        try: return dict(self.pip_browser().reset(), saved_logins_available=self.login_store().available)
        except (OSError, ValueError, CDPError): error(400, 'Pip browser profile could not be reset. Close its window and check its status.')

    def saved_login_list(self):
        store = self.login_store()
        try: return {'available': store.available, 'logins': store.list()}
        except LoginError: error(400, 'Unlock the OS password vault to view saved logins.')

    def saved_login_add(self, body):
        try:
            self.login_store().add(body.get('site'), body.get('username'), body.get('password'), body.get('subdomains', []))
            return {'ok': True}
        except LoginError as exc: error(400, str(exc))
        finally: body.pop('password', None)

    def saved_login_delete(self, body):
        try:
            self.login_store().delete(body.get('id'))
            return {'ok': True}
        except LoginError as exc: error(400, str(exc))

    def browser_post_routes(self):
        return {'/api/pip-browser/open': self.pip_browser_open, '/api/pip-browser/reset': self.pip_browser_reset,
                '/api/saved-logins/add': self.saved_login_add, '/api/saved-logins/delete': self.saved_login_delete,
                '/api/browser-card': self.browser_card}

    def browser_get_routes(self):
        return {'/api/pip-browser': self.pip_browser_status, '/api/saved-logins': self.saved_login_list}

    def browser_cli(self, engine, agent):
        """Only Hub's own browser tools are approved, per invocation."""
        sealed = agent.get('private_pip') or agent.get('draft_only')
        if sealed:
            flags = ['--no-chrome'] if engine == 'claude' else []
            return flags, 'Browser automation is disabled for Private Pip and Draft only. Do not claim browser tools are available. The owner must handle sign-in sites manually.\n'
        if not agent.get('chrome'): return [], ''
        mcp = installed_mcp(self.config)
        if not mcp:
            raise RuntimeError('Pip browser tools are not installed locally. Install Chrome DevTools MCP, or turn off Can use Pip browser in Pip settings.')
        try:
            _, socket_path = self.pip_browser().ensure()
            command, args = pip_mcp_command(mcp, socket_path)
        except (OSError, ValueError, CDPError, PipeError):
            raise RuntimeError('Pip browser tools could not start. Check Settings → Connections, or turn off Can use Pip browser.') from None
        if engine == 'claude':
            flags = ['--mcp-config', json.dumps({'mcpServers': {'chrome-devtools': {'command': command, 'args': args}}}),
                     '--allowedTools', 'mcp__chrome-devtools__*']
        else:
            # Entire Hub-owned table replaces inherited transport/tool rules only
            # for this server. Normal user settings and permission mode survive.
            table = '{command=' + json.dumps(command) + ',args=' + json.dumps(args) + ',env={CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS="1"},default_tools_approval_mode="approve",tools={}}'
            flags = ['-c', 'mcp_servers.chrome-devtools=' + table]
        return flags, BROWSER_PROMPT + 'Your Pip browser MCP is chrome-devtools, connected through the Hub private socket. After a filled status, click Sign in in the same tab; do not navigate or reload.\n'

    def browser_card(self, body):
        mid, index, action = body.get('message_id'), body.get('index'), body.get('action')
        if type(mid) is not int or type(index) is not int or action not in ('open', 'done', 'approve', 'dont'):
            error(400, 'Choose a browser request and action.')
        with self.lock:
            row = self.db.execute("SELECT * FROM messages WHERE id=? AND role='assistant'", (mid,)).fetchone()
            cards = json.loads(row['cards']) if row else []
            if not 0 <= index < len(cards) or cards[index].get('kind') not in ('signin_request', 'login_fill_request'): error(404, 'Browser request not found.')
            card = cards[index]
            cid, aid = row['chat_id'], row['agent_id']
            if aid not in self.chat(cid)['agents'] or aid not in self.agents(): error(404, 'Requesting Pip is unavailable.')
            signin = card['kind'] == 'signin_request'
            if action not in (('open', 'done') if signin else ('approve', 'dont')): error(400, 'Invalid browser action.')
            allowed = ('pending', 'opened') if signin else ('pending',)
            if card.get('status') not in allowed:
                if card.get('notification') == 'pending': self._browser_deliver(mid, index)
                return {'card': card, 'duplicate': True}
            if action == 'done' or action == 'dont':
                card['status'] = 'done' if signin else 'declined'
                result = 'I signed in to ' + card['site'] if signin else 'Saved login declined'
                card['result'], card['notification'] = result, 'pending'
                self._browser_save(mid, cards)
                reply = self._browser_deliver(mid, index)
                return {'card': card, **reply}
            card['status'] = 'opening' if action == 'open' else 'filling'
            # Claim before any side effect. Interrupted claims never automatically
            # retry a credential fill, even after a restart or repeated phone tap.
            self._browser_save(mid, cards)
        result = 'Browser action interrupted; inspect the Pip browser.'
        try:
            if action == 'open':
                self.pip_browser().open(card['site'], requester=aid)
                status = 'opened'; result = 'Pip browser window opened on the host computer.'
            else:
                store = self.login_store()
                choices = [x for x in store.list() if login_allows_site(x, card['site'])]
                identifier = body.get('login_id')
                chosen = next((x for x in choices if x['id'] == identifier), None)
                if not chosen:
                    result = 'No saved login for ' + card['site'] + ' — refused'
                else:
                    login = store.get(chosen['id'])
                    try: result = self.pip_browser().fill(login, requester=aid, site=card['site'])
                    finally: login.clear()
                if result == 'Filled': result = FILLED
                status = 'filled' if result == FILLED else 'refused'
        except (OSError, ValueError, CDPError): status = 'interrupted'
        with self.lock:
            # Re-read after I/O so unrelated cards' concurrent decisions survive.
            current = self.db.execute('SELECT cards FROM messages WHERE id=?', (mid,)).fetchone()
            cards = json.loads(current['cards']); card = cards[index]
            card['status'], card['result'] = status, result
            if action == 'approve': card['notification'] = 'pending'
            self._browser_save(mid, cards)
            reply = self._browser_deliver(mid, index) if action == 'approve' else {}
        return {'card': card, **reply}

    def _browser_save(self, mid, cards):
        self.db.execute('UPDATE messages SET cards=? WHERE id=?', (json.dumps(cards), mid))
        self.db.commit()
        self.emit('message')

    def _browser_deliver(self, mid, index):
        # Reply-to pins group routing to the Pip that requested the login. No
        # username, password, account ID or vault metadata enters this prompt.
        row = self.db.execute('SELECT chat_id,cards FROM messages WHERE id=?', (mid,)).fetchone()
        cards = json.loads(row['cards']); card = cards[index]
        if card.get('notification') != 'pending': return {}
        result = self.send({'chat_id': row['chat_id'], 'text': card['result'], 'reply_to': mid,
                            'request_id': 'browser-card-' + str(mid) + '-' + str(index) + '-result'})
        card['notification'] = 'sent'
        self._browser_save(mid, cards)
        return result

    def reconcile_browser_notifications(self):
        """Recover only certain status replies. Never replay any browser action."""
        with self.lock:
            rows = self.db.execute("SELECT id,cards FROM messages WHERE role='assistant' AND cards LIKE '%\"notification\": \"pending\"%'").fetchall()
            for row in rows:
                for index, card in enumerate(json.loads(row['cards'])):
                    if card.get('kind') in ('signin_request', 'login_fill_request') and card.get('notification') == 'pending':
                        try: self._browser_deliver(row['id'], index)
                        except Exception:
                            # A removed Pip or full queue leaves the safe status
                            # pending; a later card tap can retry notification.
                            pass
