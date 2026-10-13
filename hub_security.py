"""Small, standard-library security controls for the single-owner Hub."""

from contextlib import contextmanager
from collections import deque
import hashlib
import hmac
from http.cookies import SimpleCookie, CookieError
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import hub_fs
from hub_process import run_bounded
import threading
import time
from http.server import ThreadingHTTPServer


HEADER_SECONDS = 10
MAX_HANDLERS = 48  # Includes at most 20 long-lived SSE connections.
MAX_UNAUTH_PER_IP = 8
AUTH_RESERVED_HANDLERS = 32  # 20 event streams plus room for active owner requests.
BODY_SECONDS = 30
UPLOAD_MIN_BYTES_PER_SECOND = 32 * 1024
UPLOAD_RETENTION_SECONDS = 24 * 3600
LOGIN_WINDOW_SECONDS = 60
LOGIN_MAX_FAILURES = 10
LOGIN_MAX_KEYS = 512
LOGIN_GLOBAL_FAILURES = 100


class DeadlineReader:
    """Apply one wall-clock deadline across the request line and all headers."""

    def __init__(self, reader, connection, deadline):
        self.reader = reader
        self.connection = connection
        self.deadline = deadline

    def _timeout(self):
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout('Request headers timed out.')
            self.connection.settimeout(remaining)

    def readline(self, *args, **kwargs):
        self._timeout()
        return self.reader.readline(*args, **kwargs)

    def read(self, *args, **kwargs):
        self._timeout()
        return self.reader.read(*args, **kwargs)


class HeaderDeadlineMixin:
    """Put before BaseHTTPRequestHandler in the handler inheritance list."""

    def handle_one_request(self):
        original = self.rfile
        self.rfile = DeadlineReader(original, self.connection, time.monotonic() + HEADER_SECONDS)
        self._header_gate = threading.Lock()
        self._header_active = True
        def expire():
            with self._header_gate:
                if self._header_active:
                    try:
                        self.connection.shutdown(socket.SHUT_RD)
                    except OSError:
                        pass
        self._header_timer = threading.Timer(HEADER_SECONDS, expire)
        self._header_timer.daemon = True
        self._header_timer.start()
        try:
            return super().handle_one_request()
        except (socket.timeout, TimeoutError):
            self.close_connection = True
        finally:
            with self._header_gate:
                self._header_active = False
            self._header_timer.cancel()
            self.rfile = original

    def parse_request(self):
        try:
            return super().parse_request()
        finally:
            with self._header_gate:
                self._header_active = False
            self._header_timer.cancel()
            self.rfile.deadline = None
            self.connection.settimeout(30)


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Reject excess sockets before spawning threads, including slow headers."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, *args, max_handlers=MAX_HANDLERS,
                 max_unauth_per_ip=MAX_UNAUTH_PER_IP,
                 auth_reserved_handlers=AUTH_RESERVED_HANDLERS, **kwargs):
        if max_handlers < 21:
            raise ValueError('max_handlers must leave room for 20 event streams and one request')
        if not 0 < auth_reserved_handlers < max_handlers or max_unauth_per_ip < 1:
            raise ValueError('Invalid connection admission limits')
        self._handler_slots = threading.BoundedSemaphore(max_handlers)
        self._admission_lock = threading.Lock()
        self._admitted = {}
        self._unauth_by_ip = {}
        self._unauth_total = 0
        self._unauth_limit = max_handlers - auth_reserved_handlers
        self._max_unauth_per_ip = max_unauth_per_ip
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._handler_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        ip = client_address[0]
        with self._admission_lock:
            authenticated = self._authenticated_on_arrival(request)
            admitted = authenticated or (self._unauth_total < self._unauth_limit and
                        self._unauth_by_ip.get(ip, 0) < self._max_unauth_per_ip)
            if admitted:
                self._admitted[id(request)] = None if authenticated else ip
                if not authenticated:
                    self._unauth_total += 1
                    self._unauth_by_ip[ip] = self._unauth_by_ip.get(ip, 0) + 1
        if not admitted:
            self._handler_slots.release()
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._release_admission(request)
            self._handler_slots.release()
            raise

    def _authenticated_on_arrival(self, request):
        """Use only immediately available complete headers for reserved capacity."""
        try:
            data = request.recv(8192, socket.MSG_PEEK | socket.MSG_DONTWAIT)
            head, marker, _ = data.partition(b'\r\n\r\n')
            if not marker or b'\r\n' not in head:
                return False
            cookie_headers = [line[7:].strip() for line in head.split(b'\r\n')[1:]
                              if line.lower().startswith(b'cookie:')]
            if len(cookie_headers) != 1:
                return False
            cookies = SimpleCookie(cookie_headers[0].decode('latin-1'))
            token = cookies['hub_session'].value if 'hub_session' in cookies else ''
            return bool(token and self.hub.authenticated(token))
        except (AttributeError, CookieError, OSError, ValueError):
            return False

    def mark_authenticated(self, request):
        """Release this socket's unauthenticated quota after a valid session check."""
        with self._admission_lock:
            ip = self._admitted.get(id(request))
            if ip is not None:
                self._unauth_total -= 1
                self._unauth_by_ip[ip] -= 1
                if not self._unauth_by_ip[ip]: del self._unauth_by_ip[ip]
                self._admitted[id(request)] = None

    def _release_admission(self, request):
        with self._admission_lock:
            ip = self._admitted.pop(id(request), None)
            if ip is not None:
                self._unauth_total -= 1
                self._unauth_by_ip[ip] -= 1
                if not self._unauth_by_ip[ip]: del self._unauth_by_ip[ip]

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._release_admission(request)
            self._handler_slots.release()

    def handle_error(self, request, client_address):
        """Browser disconnects are routine and should not emit tracebacks."""
        import sys
        error_type = sys.exc_info()[0]
        if error_type is not None and issubclass(error_type, (BrokenPipeError, ConnectionResetError,
                                                             ConnectionAbortedError, TimeoutError)):
            return
        return super().handle_error(request, client_address)


def read_body_with_deadline(reader, connection, length, deadline_seconds=BODY_SECONDS):
    """Read exactly length bytes within one wall-clock deadline, even if peer trickles."""
    return b''.join(iter_body_chunks(reader, connection, length, deadline_seconds))


def iter_body_chunks(reader, connection, length, deadline_seconds=BODY_SECONDS):
    """Yield body chunks under a shared deadline for streaming uploads."""
    deadline = time.monotonic() + deadline_seconds
    expired = threading.Event()
    def stop_read():
        expired.set()
        try:
            connection.shutdown(socket.SHUT_RD)
        except (OSError, AttributeError):
            pass
    timer = threading.Timer(deadline_seconds, stop_read)
    timer.daemon = True
    timer.start()
    remaining = length
    try:
        while remaining:
            seconds = deadline - time.monotonic()
            if seconds <= 0 or expired.is_set():
                raise socket.timeout('Request body timed out.')
            connection.settimeout(seconds)
            try:
                chunk = reader.read(min(remaining, 65536))
            except socket.timeout:
                raise socket.timeout('Request body timed out.')
            if expired.is_set():
                raise socket.timeout('Request body timed out.')
            if not chunk:
                raise EOFError('Request body ended early.')
            remaining -= len(chunk)
            yield chunk
    finally:
        timer.cancel()
        connection.settimeout(30)


def upload_deadline_seconds(length):
    return max(BODY_SECONDS, length / UPLOAD_MIN_BYTES_PER_SECOND)


_BASE_ENV = frozenset(('PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LANGUAGE',
                       'TERM', 'TMPDIR', 'TMP', 'TEMP', 'SHELL'))
_PROVIDER_PREFIXES = ('ANTHROPIC_', 'CLAUDE_', 'OPENAI_', 'CODEX_')


def allowed_agent_environment(environ=None):
    """Pass only CLI runtime and documented provider credential namespaces."""
    source = os.environ if environ is None else environ
    return {key: value for key, value in source.items()
            if key in _BASE_ENV or key.startswith('LC_') or
            key.startswith(_PROVIDER_PREFIXES)}


_SENSITIVE_DIRS = frozenset(('.ssh', '.gnupg', '.aws', '.config', '.claude',
                             '.codex', '.kube', '.local', '.npm', '.docker',
                             'Library', 'Keychains'))


def validate_safe_workdir(raw, home=None):
    """Resolve a project directory within home, away from credential stores."""
    if not isinstance(raw, (str, Path)) or not str(raw).strip() or '\x00' in str(raw):
        raise ValueError('Choose a working folder.')
    home = Path.home().resolve() if home is None else Path(home).resolve()
    folder = Path(raw).expanduser().resolve()
    try:
        parts = folder.relative_to(home).parts
    except ValueError:
        raise ValueError('Working folder must be inside your home folder.')
    if any(part.casefold() in {name.casefold() for name in _SENSITIVE_DIRS} for part in parts):
        raise ValueError('Choose a project folder outside private settings.')
    if not folder.is_dir():
        raise ValueError('Working folder does not exist.')
    return folder


@contextmanager
def open_validated_file(path, roots):
    """Open a regular file beneath an allowed root without following any symlink."""
    from hub import HubError
    try:
        fd = _open_validated_fd(path, roots)
    except (OSError, ValueError):
        raise HubError(403, 'File path is not allowed.')
    with os.fdopen(fd, 'rb') as stream:
        yield stream


@contextmanager
def open_directory_fd(path):
    """Compatibility context for the shared pinned-directory implementation."""
    fd = hub_fs.open_directory(path)
    try:
        yield fd
    finally:
        os.close(fd)


def _open_validated_fd(path, roots):
    path = Path(path)
    for root in map(Path, roots):
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            continue
        if not parts or '..' in parts:
            continue
        with hub_fs.open_file(path, 'rb') as stream:
            return os.dup(stream.fileno())
    raise ValueError('File is outside allowed folders.')


class UploadQuota:
    """Reserve expected bytes under Hub's lock before an upload starts."""

    def __init__(self, hub):
        self.hub = hub
        self.pending = {}  # Path -> full declared size, guarded by hub.lock.

    def _files(self):
        with open_directory_fd(self.hub.uploads) as directory:
            for name in hub_fs.listdir_fd(directory):
                try:
                    info = hub_fs.stat_fd(directory, name)
                    if stat.S_ISREG(info.st_mode):
                        yield self.hub.uploads / name, info
                except OSError:
                    continue

    def _references(self):
        # Messages may link uploaded files in prose/cards as well as attachments.
        references = set()
        content = []
        for row in self.hub.db.execute('SELECT uploads,text,cards FROM messages'):
            try:
                for raw in json.loads(row['uploads'] or '[]'):
                    if isinstance(raw, str):
                        references.add(raw)
                        if hasattr(self.hub, 'path'):
                            try:
                                references.add(str(self.hub.path(raw)))
                            except (OSError, ValueError):
                                pass
            except (ValueError, TypeError):
                pass
            content.extend((row['text'] or '', row['cards'] or ''))
        content.extend(row[0] or '' for row in self.hub.db.execute('SELECT prompt FROM jobs'))
        return references, content

    def cleanup(self, now=None):
        """Remove only old, unreferenced, completed uploads. Caller holds hub.lock."""
        now = time.time() if now is None else now
        references, content = self._references()
        removed = 0
        with open_directory_fd(self.hub.uploads) as directory:
            for name in hub_fs.listdir_fd(directory):
                # Upload names are minted by Handler.upload; never delete arbitrary files.
                if not re.fullmatch(r'[0-9a-f]{24}-.{1,150}', name):
                    continue
                p = self.hub.uploads / name
                try:
                    info = hub_fs.stat_fd(directory, name)
                    if (not stat.S_ISREG(info.st_mode) or p in self.pending or str(p) in references or
                            any(str(p) in blob for blob in content) or
                            now - info.st_mtime < UPLOAD_RETENTION_SECONDS):
                        continue
                    hub_fs.unlink_fd(directory, name, generated=True)
                    removed += 1
                except OSError:
                    continue
        return removed

    @contextmanager
    def reserve(self, path, size):
        """Raise hub.HubError(413) when the aggregate disk quota cannot fit size."""
        from hub import HubError
        path = Path(path)
        if size <= 0 or path.parent != self.hub.uploads:
            raise ValueError('Invalid upload reservation')
        with self.hub.lock:
            self.cleanup()
            disk = sum(s.st_size for p, s in self._files() if p not in self.pending)
            used = disk + sum(self.pending.values())
            limit = int(self.hub.config['max_total_upload_bytes'])
            if size > limit - used:
                raise HubError(413, 'Upload storage quota reached. Remove unused uploads or increase max_total_upload_bytes.')
            self.pending[path] = size
        try:
            yield
        finally:
            with self.hub.lock:
                self.pending.pop(path, None)


class LoginLimiter:
    """Throttle guesses by submitted-token digest, independent of proxy peer."""

    def __init__(self):
        self.failures = {}  # Digest -> (count, first-attempt monotonic time)
        self.recent = deque(maxlen=LOGIN_GLOBAL_FAILURES + 1)
        self.lock = threading.Lock()

    def check(self, token, expected_hex, now=None):
        """Return (valid, retry_seconds); valid owner token always bypasses limits."""
        now = time.monotonic() if now is None else now
        supplied = token if isinstance(token, str) else ''
        digest = hashlib.sha256(supplied.encode()).hexdigest()
        if isinstance(token, str) and hmac.compare_digest(digest, expected_hex):
            return True, 0
        with self.lock:
            self.failures = {k: v for k, v in self.failures.items() if now - v[1] < LOGIN_WINDOW_SECONDS}
            while self.recent and now - self.recent[0] >= LOGIN_WINDOW_SECONDS:
                self.recent.popleft()
            self.recent.append(now)
            count, first = self.failures.get(digest, (0, now))
            count += 1
            if digest not in self.failures and len(self.failures) >= LOGIN_MAX_KEYS:
                oldest = min(self.failures, key=lambda k: self.failures[k][1])
                del self.failures[oldest]
            self.failures[digest] = (count, first)
            if count > LOGIN_MAX_FAILURES or len(self.recent) > LOGIN_GLOBAL_FAILURES:
                return False, max(1, int(LOGIN_WINDOW_SECONDS - (now - first)))
            return False, 0


def tailscale_serve_plan(config, status):
    """Pure preview of Serve setup; never changes Tailscale or config."""
    if config.get('bind') != '127.0.0.1':
        raise ValueError('Tailscale Serve requires Hub bound to 127.0.0.1.')
    if status.get('BackendState') != 'Running':
        raise ValueError('Tailscale is not running.')
    host = str(status.get('Self', {}).get('DNSName', '')).rstrip('.').lower()
    if not re.fullmatch(r'[a-z0-9-]+(?:\.[a-z0-9-]+)+', host):
        raise ValueError('Tailscale did not report a valid device DNS name.')
    port = int(config['port'])
    if not 1 <= port <= 65535:
        raise ValueError('Invalid Hub port.')
    origin = 'https://' + host
    return {
        'origin': origin,
        'command': ['tailscale', 'serve', '--bg', 'http://127.0.0.1:%d' % port],
        'allowed_origins': list(dict.fromkeys(list(config.get('allowed_origins', [])) + [origin])),
    }


def local_tailscale_status(run=run_bounded):
    """Ask the local Tailscale daemon for status; only call for --tailscale CLI."""
    result = run(['tailscale', 'status', '--json'], text=True, timeout=5, check=True)
    return json.loads(result.stdout)
