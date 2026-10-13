"""Small loopback-only CDP client and owner-tapped top-document login fill."""
import base64
import hashlib
import json
import os
import socket
import struct
import time
from urllib.parse import urlsplit

from hub_login import is_local_host


class CDPError(RuntimeError):
    pass


class CDPClient:
    def __init__(self, endpoint, timeout=5):
        url = urlsplit(endpoint)
        if url.scheme != 'ws' or url.hostname != '127.0.0.1' or not url.port or url.username or url.password or url.fragment:
            raise CDPError('Refused a non-loopback browser connection.')
        self.socket = socket.create_connection(('127.0.0.1', url.port), timeout)
        self.socket.settimeout(timeout)
        self.counter = 0
        self.buffer = b''
        self.timeout = timeout
        try:
            key = base64.b64encode(os.urandom(16)).decode()
            path = url.path + ('?' + url.query if url.query else '')
            request = ('GET ' + path + ' HTTP/1.1\r\nHost: 127.0.0.1:' + str(url.port) +
                       '\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: ' + key +
                       '\r\nSec-WebSocket-Version: 13\r\n\r\n')
            self.socket.sendall(request.encode('ascii'))
            data = b''
            while b'\r\n\r\n' not in data:
                chunk = self.socket.recv(4096)
                if not chunk or len(data) > 16384: raise CDPError('Browser handshake failed.')
                data += chunk
            header, self.buffer = data.split(b'\r\n\r\n', 1)
            lines = header.decode('ascii').split('\r\n')
            headers = {k.lower(): v.strip() for k, v in (line.split(':', 1) for line in lines[1:] if ':' in line)}
            expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            if ' 101 ' not in lines[0] or headers.get('sec-websocket-accept') != expected:
                raise CDPError('Browser handshake failed.')
        except Exception:
            self.socket.close()
            raise CDPError('Browser connection failed.') from None

    def close(self): self.socket.close()
    def __enter__(self): return self
    def __exit__(self, *args): self.close()

    def _read(self, n):
        while len(self.buffer) < n:
            chunk = self.socket.recv(max(4096, n - len(self.buffer)))
            if not chunk: raise CDPError('Browser connection closed.')
            self.buffer += chunk
        result, self.buffer = self.buffer[:n], self.buffer[n:]
        return result

    def _send(self, payload, opcode=1):
        mask = os.urandom(4)
        size = len(payload)
        header = bytes([0x80 | opcode])
        if size < 126: header += bytes([0x80 | size])
        elif size < 65536: header += bytes([0x80 | 126]) + struct.pack('!H', size)
        else: header += bytes([0x80 | 127]) + struct.pack('!Q', size)
        self.socket.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def _message(self):
        chunks = []
        total = 0
        while True:
            a, b = self._read(2)
            size = b & 127
            if size == 126: size = struct.unpack('!H', self._read(2))[0]
            if size == 127: size = struct.unpack('!Q', self._read(8))[0]
            if size > 2 * 1024 * 1024 or total + size > 2 * 1024 * 1024: raise CDPError('Browser reply too large.')
            if b & 128: raise CDPError('Invalid browser frame.')
            payload = self._read(size)
            opcode = a & 15
            if opcode == 8: raise CDPError('Browser connection closed.')
            if opcode == 9: self._send(payload, 10); continue
            if opcode == 10: continue
            if opcode not in (0, 1): raise CDPError('Invalid browser frame.')
            chunks.append(payload); total += size
            if a & 128: return b''.join(chunks)

    def call(self, method, params=None):
        self.counter += 1
        identifier = self.counter
        try:
            self._send(json.dumps({'id': identifier, 'method': method, 'params': params or {}}).encode())
            until = time.monotonic() + self.timeout
            for _ in range(1000):
                self.socket.settimeout(max(.01, until - time.monotonic()))
                if time.monotonic() >= until: raise CDPError('Browser response timed out.')
                message = json.loads(self._message())
                if message.get('id') != identifier: continue
                if message.get('error'): raise CDPError('Browser action refused.')
                return message.get('result') or {}
            raise CDPError('Browser response timed out.')
        except (OSError, ValueError, TypeError): raise CDPError('Browser action could not be completed.') from None


def origin_matches(url, login):
    try:
        parsed = urlsplit(url)
        saved = urlsplit('//' + login['site'])
        allowed = [saved.hostname] + login.get('subdomains', [])
        if parsed.hostname not in allowed or parsed.username is not None or parsed.password is not None:
            return False
        if is_local_host(saved.hostname):
            if saved.hostname == '::1' and parsed.netloc.lower() not in ('[::1]', '[::1]:' + str(parsed.port)):
                return False
            port = parsed.port if parsed.port is not None else {'http': 80, 'https': 443}.get(parsed.scheme)
            return (parsed.scheme in ('http', 'https') and saved.port is not None
                    and parsed.hostname == saved.hostname and port == saved.port)
        return parsed.scheme == 'https' and parsed.port in (None, 443)
    except (ValueError, KeyError): return False


def _tab_location(url):
    """Describe a checked tab by host and port only; paths can carry one-time tokens."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or 'unknown host'
        if ':' in host: host = '[' + host + ']'
        port = ':' + str(parsed.port) if parsed.port is not None else ''
        return (host + port)[:280]
    except ValueError:
        return 'unknown page'


FILLED = "Filled — now click Sign in; don't reload"

# The object is resolved from the pinned top-document DOM node in an isolated
# world. Validation and the native setter execute in ONE operation: focus is
# never used as the credential destination. Page handlers may observe their own
# login fields, but cannot redirect this setter into another document or iframe.
SET_LOGIN_FIELD = r"""function(value, expectedURL, password) {
  if (window !== window.top || this.ownerDocument !== document ||
      !this.isConnected || document.location.href !== expectedURL ||
      this.tagName !== 'INPUT' || this.disabled || this.readOnly ||
      (password ? this.type !== 'password' : !['text','email','tel'].includes(this.type))) return false;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(this, value);
  this.dispatchEvent(new Event('input', {bubbles:true}));
  this.dispatchEvent(new Event('change', {bubbles:true}));
  return true;
}"""


def fill_login(client, login, expected_url=None):
    """Resolve both top-document fields before releasing values; never focus/type."""
    site = login['site']
    def frame():
        return client.call('Page.getFrameTree').get('frameTree', {}).get('frame', {})
    initial = frame()
    def refused(reason, url=None):
        return reason + " in the Pip's login tab (" + _tab_location(initial.get('url', '') if url is None else url) + ') — refused'
    if expected_url is not None and initial.get('url') != expected_url:
        return refused('Page navigated before filling')
    if not origin_matches(initial.get('url', ''), login): return refused('Page is not on ' + site)
    root = client.call('DOM.getDocument', {'depth': 0})['root']['nodeId']
    def fields(selector, password=False):
        nodes = client.call('DOM.querySelectorAll', {'nodeId': root, 'selector': selector}).get('nodeIds', [])
        valid = []
        for identifier in nodes[:20]:
            info = client.call('DOM.describeNode', {'nodeId': identifier}).get('node', {})
            attrs = info.get('attributes', [])
            attrs = dict(zip(attrs[::2], attrs[1::2]))
            if info.get('nodeName', '').upper() != 'INPUT' or 'disabled' in attrs or 'readonly' in attrs: continue
            if password and attrs.get('type', '').lower() != 'password': continue
            if not password and attrs.get('type', 'text').lower() not in ('text', 'email', 'tel'): continue
            valid.append(identifier)
        return valid
    passwords = fields('input[type="password"]', True)
    users = fields('input[autocomplete="username"],input[type="email"],input[name="username"],input[name="email"],input[id="username"],input[id="email"]')
    if not users: users = fields('input[type="text"],input:not([type])')
    if len(users) != 1 or len(passwords) != 1:
        return refused('No login form found')
    world = client.call('Page.createIsolatedWorld', {'frameId': initial['id'], 'worldName': 'agent-hub-login'})
    context = world.get('executionContextId')
    if type(context) is not int: return refused('Login document changed')
    for identifier, value, password in ((users[0], login['username'], False), (passwords[0], login['password'], True)):
        current = frame()
        if current.get('id') != initial.get('id') or current.get('url') != initial.get('url') or not origin_matches(current.get('url', ''), login):
            return refused('Page navigated away from ' + site, current.get('url', ''))
        obj = client.call('DOM.resolveNode', {'nodeId': identifier, 'executionContextId': context}).get('object', {}).get('objectId')
        if not obj: return refused('Login field was replaced')
        try:
            result = client.call('Runtime.callFunctionOn', {'objectId': obj,
                'functionDeclaration': SET_LOGIN_FIELD, 'returnByValue': True,
                'arguments': [{'value': value}, {'value': initial['url']}, {'value': password}]})
            if result.get('exceptionDetails') or result.get('result', {}).get('value') is not True:
                return refused('Login field or top-level document changed')
        finally: client.call('Runtime.releaseObject', {'objectId': obj})
    return FILLED
