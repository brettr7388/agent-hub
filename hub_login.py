"""Opt-in OS vault. Credentials and account metadata never enter Hub storage."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading


class LoginError(ValueError):
    """Safe to display: never contains a credential or CLI diagnostic."""


def _host(value):
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 253:
        raise LoginError('Enter an exact domain, or localhost:port for a local site.')
    if value.startswith('['):
        if value.lower() == '[::1]': return '[::1]'  # legacy vault entry
        match = re.fullmatch(r'\[::1\]:([0-9]+)', value.lower())
        if not match or not 1 <= int(match[1]) <= 65535:
            raise LoginError('Use [::1]:port with a port from 1 to 65535.')
        return '[::1]:' + str(int(match[1]))
    if ':' in value:
        host, port = value.lower().split(':', 1)
        if not _local_host(host) or not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
            raise LoginError('Use a local host and a port from 1 to 65535.')
        value = host + ':' + str(int(port))
    else:
        host = value
    try: value = value.lower().encode('idna').decode('ascii')
    except UnicodeError: raise LoginError('Enter a valid domain.') from None
    if _local_host(host.lower()):
        labels = host.lower().split('.')
        if any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in labels):
            raise LoginError('Enter an exact local host.')
        return value
    if any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part) for part in value.split('.')):
        raise LoginError('Enter an exact domain, without a URL, path or port.')
    return value


def is_local_host(host):
    """Recognize exact local hostnames (without a port), including IPv6 loopback."""
    return isinstance(host, str) and (host in ('localhost', '127.0.0.1', '::1') or
                                      host.endswith('.localhost'))


_local_host = is_local_host


def _local_site(site):
    site = site.lower()
    if site.startswith('[::1]'):
        return '::1', site[6:] if site.startswith('[::1]:') else None
    host, separator, port = site.partition(':')
    return (host, port if separator else None) if _local_host(host) else (None, None)


# Offline Public Suffix List (MPL 2.0), including private suffixes. No lookup requests.
_RULES = None
def _suffix_rules():
    global _RULES
    if _RULES is None:
        exact, wildcard, exceptions = set(), set(), set()
        for raw in (Path(__file__).parent / 'docs/public-suffix-list.dat').read_text().splitlines():
            raw = raw.strip()
            if not raw or raw.startswith('//'): continue
            target = exceptions if raw.startswith('!') else wildcard if raw.startswith('*.') else exact
            target.add(raw.lstrip('!').removeprefix('*.').encode('idna').decode('ascii').lower())
        _RULES = exact, wildcard, exceptions
    return _RULES


def validate_site(value, *, allow_legacy_local=False):
    site = _host(value)
    host, port = _local_site(site)
    if host:
        if not port and not allow_legacy_local:
            raise LoginError('Enter a port from 1 to 65535 for a local site.')
        return site
    labels = site.split('.')
    exact, wildcard, exceptions = _suffix_rules()
    suffix = 1
    for i in range(len(labels)):
        tail = '.'.join(labels[i:])
        if tail in exceptions:
            suffix = len(labels) - i - 1
            break
        if tail in exact: suffix = max(suffix, len(labels) - i)
        if i > 0 and tail in wildcard: suffix = max(suffix, len(labels) - i + 1)
    if len(labels) != suffix + 1:
        raise LoginError('Use the exact registrable domain; list subdomains separately.')
    return site


def validate_subdomains(site, values, *, allow_legacy_local=False):
    site = validate_site(site, allow_legacy_local=allow_legacy_local)
    if not isinstance(values, list) or len(values) > 20:
        raise LoginError('List up to 20 exact subdomains.')
    result = []
    for value in values:
        host = _host(value)
        if _local_site(site)[0] or host == site or not host.endswith('.' + site):
            raise LoginError('Each allowed subdomain must belong to the saved domain.')
        if host not in result: result.append(host)
    return result


def login_allows_site(login, site):
    """Offer local logins only for the saved host and explicit port."""
    site = _host(site)
    saved = _host(login['site'])
    if _local_site(saved)[0] and not _local_site(saved)[1]: return False
    return site == saved or site in login.get('subdomains', [])


class LoginStore:
    SERVICE = 'Agent Hub'
    INDEX = '__saved_logins__'

    def __init__(self, platform=None, binary=None):
        self.platform = platform or sys.platform
        name = 'security' if self.platform == 'darwin' else 'secret-tool' if self.platform.startswith('linux') else ''
        self.binary = binary or (shutil.which(name) if name else None)
        self.available = bool(name and self.binary)
        self.lock = threading.RLock()

    def _run(self, args, text=None):
        if not self.available: raise LoginError('Saved logins are unavailable on this computer.')
        try:
            result = subprocess.run([self.binary] + args, input=text, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        except (OSError, subprocess.SubprocessError):
            raise LoginError('The OS password vault could not complete this action.') from None
        return result

    def _read(self, account):
        args = ['find-generic-password', '-s', self.SERVICE, '-a', account, '-w'] if self.platform == 'darwin' else ['lookup', 'service', self.SERVICE, 'account', account]
        result = self._run(args)
        if result.returncode == (44 if self.platform == 'darwin' else 1): return None
        if result.returncode: raise LoginError('Unlock the OS password vault and try again.')
        # Both CLI tools append one newline. Do not strip whitespace in passwords.
        return result.stdout[:-1] if result.stdout.endswith('\n') else result.stdout

    def _write(self, account, value):
        if self.platform == 'darwin':
            # -i reads commands from stdin. Hex -X avoids quoting/control-character
            # ambiguity, and neither the secret nor its encoding appears in argv.
            quote = lambda x: '"' + x.replace('\\', '\\\\').replace('"', '\\"') + '"'
            command = 'add-generic-password -U -s ' + quote(self.SERVICE) + ' -a ' + quote(account) + ' -X ' + value.encode('utf-8').hex() + '\n'
            result = self._run(['-i'], command)
        else:
            result = self._run(['store', '--label=Agent Hub', 'service', self.SERVICE, 'account', account], value)
        if result.returncode or self._read(account) != value:
            raise LoginError('The OS password vault did not save this login.')

    def _index(self):
        raw = self._read(self.INDEX)
        if raw is None: return []
        try:
            items = json.loads(raw)
            if not isinstance(items, list) or len(items) > 200: raise ValueError()
            for item in items:
                if set(item) != {'id', 'site', 'username', 'subdomains'}: raise ValueError()
                validate_site(item['site'], allow_legacy_local=True)
                validate_subdomains(item['site'], item['subdomains'], allow_legacy_local=True)
                if not isinstance(item['username'], str) or not isinstance(item['id'], str): raise ValueError()
            return items
        except (ValueError, TypeError, KeyError): raise LoginError('Saved-login metadata could not be read.') from None

    def list(self):
        if not self.available: return []
        with self.lock:
            return [dict(item, needs_port=bool(_local_site(item['site'])[0] and
                                                not _local_site(item['site'])[1]))
                    for item in self._index()]

    def add(self, site, username, password, subdomains=None):
        site = validate_site(site)
        subdomains = validate_subdomains(site, subdomains or [])
        if not isinstance(username, str) or not username.strip() or len(username) > 320 or any(c in username for c in '\x00\r\n'):
            raise LoginError('Enter a username.')
        if not isinstance(password, str) or not password or len(password) > 4096 or '\x00' in password:
            raise LoginError('Enter a password of at most 4096 characters.')
        account = site + ':' + username
        item = {'id': hashlib.sha256(account.encode()).hexdigest(), 'site': site, 'username': username, 'subdomains': subdomains}
        with self.lock:
            items = self._index()
            if len(items) >= 200 and not any(x['id'] == item['id'] for x in items): raise LoginError('Saved-login limit reached.')
            self._write(account, password)
            items = [x for x in items if x['id'] != item['id']] + [item]
            self._write(self.INDEX, json.dumps(items, ensure_ascii=False))
        return item

    def get(self, identifier):
        with self.lock:
            item = next((x for x in self._index() if x['id'] == identifier), None)
            if not item: raise LoginError('Saved login not found.')
            if _local_site(item['site'])[0] and not _local_site(item['site'])[1]:
                raise LoginError('Add a port before using this saved local login.')
            password = self._read(item['site'] + ':' + item['username'])
            if password is None: raise LoginError('Saved login not found.')
            return dict(item, password=password)

    def delete(self, identifier):
        with self.lock:
            items = self._index()
            item = next((x for x in items if x['id'] == identifier), None)
            if not item: raise LoginError('Saved login not found.')
            account = item['site'] + ':' + item['username']
            self._delete_account(account)
            remaining = [x for x in items if x['id'] != identifier]
            if remaining: self._write(self.INDEX, json.dumps(remaining, ensure_ascii=False))
            else: self._delete_account(self.INDEX)

    def _delete_account(self, account):
        args = ['delete-generic-password', '-s', self.SERVICE, '-a', account] if self.platform == 'darwin' else ['clear', 'service', self.SERVICE, 'account', account]
        result = self._run(args)
        if result.returncode not in (0, 44 if self.platform == 'darwin' else 1):
            raise LoginError('Saved login could not be deleted.')
