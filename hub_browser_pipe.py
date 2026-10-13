"""Private Chrome remote-debugging-pipe broker for the Pip browser.

Chrome has exactly one CDP pipe peer: this process. Local clients use a
WebSocket endpoint on a mode-0600 Unix socket in a mode-0700 directory.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import socketserver
import stat
import struct
import subprocess
import sys
import threading
import time


MAX_MESSAGE = 8 * 1024 * 1024
_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


class PipeError(RuntimeError):
    pass


def _exact(sock, count, deadline=None):
    parts = []
    while count:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('CDP call timed out')
            sock.settimeout(remaining)
        chunk = sock.recv(count)
        if not chunk:
            raise EOFError('WebSocket closed')
        parts.append(chunk)
        count -= len(chunk)
    return b''.join(parts)


def _read_frame(sock, *, masked, deadline=None):
    first, second = _exact(sock, 2, deadline)
    length = second & 127
    if length == 126:
        length = struct.unpack('!H', _exact(sock, 2, deadline))[0]
    elif length == 127:
        length = struct.unpack('!Q', _exact(sock, 8, deadline))[0]
    if length > MAX_MESSAGE or bool(second & 128) != masked or not first & 128:
        raise PipeError('Invalid WebSocket frame')
    key = _exact(sock, 4, deadline) if masked else None
    body = _exact(sock, length, deadline)
    if key:
        body = bytes(value ^ key[i % 4] for i, value in enumerate(body))
    opcode = first & 15
    if opcode not in (1, 8, 9, 10):
        raise PipeError('Invalid WebSocket opcode')
    return opcode, body


def _frame(data, opcode=1, *, mask=False):
    if len(data) > MAX_MESSAGE:
        raise PipeError('WebSocket message too large')
    size = len(data)
    header = bytes([0x80 | opcode])
    marker = 0x80 if mask else 0
    if size < 126:
        header += bytes([marker | size])
    elif size < 65536:
        header += bytes([marker | 126]) + struct.pack('!H', size)
    else:
        header += bytes([marker | 127]) + struct.pack('!Q', size)
    if not mask:
        return header + data
    key = os.urandom(4)
    return header + key + bytes(value ^ key[i % 4] for i, value in enumerate(data))


def _private_socket_path(path):
    path = Path(path)
    if not path.is_absolute():
        raise PipeError('Browser socket path must be absolute')
    parent = path.parent
    current = Path(parent.anchor)
    for component in parent.parts[1:]:
        current /= component
        if stat.S_ISLNK(current.lstat().st_mode):
            raise PipeError('Browser socket directory cannot contain symlinks')
    st = parent.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
        raise PipeError('Browser socket directory must be owned by this user and mode 0700')
    if len(os.fsencode(path)) > 100:
        raise PipeError('Browser socket path is too long; use a private temporary directory')
    try:
        path.lstat()
    except FileNotFoundError:
        return path
    raise PipeError('Browser socket path already exists')


class _UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        broker = self.server.broker
        peer = self.request
        peer.settimeout(30)
        try:
            header = bytearray()
            while b'\r\n\r\n' not in header:
                chunk = peer.recv(4096)
                if not chunk or len(header) + len(chunk) > 16384:
                    return
                header.extend(chunk)
            raw, rest = bytes(header).split(b'\r\n\r\n', 1)
            if rest:
                # A pipelined frame cannot be safely handled by this socket parser.
                return
            lines = raw.decode('ascii').split('\r\n')
            fields = dict(line.split(':', 1) for line in lines[1:] if ':' in line)
            fields = {key.lower(): value.strip() for key, value in fields.items()}
            if (lines[0] != 'GET /devtools/browser/pip HTTP/1.1' or
                    fields.get('upgrade', '').lower() != 'websocket' or
                    'upgrade' not in fields.get('connection', '').lower() or
                    fields.get('sec-websocket-version') != '13'):
                return
            key = fields.get('sec-websocket-key', '')
            if len(base64.b64decode(key, validate=True)) != 16:
                return
            accept = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
            peer.sendall(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n'
                          'Connection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + '\r\n\r\n').encode())
            # Keep an idle MCP connection alive through an ordinary long turn.
            # A stalled partial frame still has a finite socket timeout.
            peer.settimeout(300)
            client = _Peer(peer)
            broker._add(client)
            try:
                broker._init_root(client)
                while broker.running:
                    opcode, body = _read_frame(peer, masked=True)
                    if opcode == 8:
                        break
                    if opcode == 9:
                        client.send_raw(body, 10)
                    elif opcode == 1:
                        try:
                            message = json.loads(body)
                        except (ValueError, UnicodeDecodeError):
                            raise PipeError('Invalid CDP message') from None
                        broker._forward(client, message)
            finally:
                broker._remove(client)
        except (OSError, EOFError, PipeError, ValueError, UnicodeError):
            return


class _Peer:
    def __init__(self, sock):
        self.sock = sock
        self.lock = threading.Lock()
        self.sessions = set()
        self.root_session = None
        self.ready = threading.Event()

    def send_raw(self, data, opcode=1):
        with self.lock:
            self.sock.sendall(_frame(data, opcode))

    def send(self, message):
        self.send_raw(json.dumps(message, separators=(',', ':')).encode())


class PipeBroker:
    """Multiplex a Chrome pipe onto a private Unix WebSocket socket."""
    def __init__(self, socket_path, command_fd, response_fd, process=None):
        try:
            self.socket_path = str(_private_socket_path(socket_path))
        except Exception:
            for fd in (command_fd, response_fd):
                try: os.close(fd)
                except OSError: pass
            raise
        self.process = process
        self._command = None
        self._response = None
        self._server = None
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._clients = set()
        self._pending = {}
        self._sessions = {}
        self._counter = 0
        self.running = False
        try:
            self._command = os.fdopen(command_fd, 'wb', buffering=0)
            self._response = os.fdopen(response_fd, 'rb', buffering=0)
            self._server = _UnixServer(self.socket_path, _Handler)
            self._server.broker = self
            os.chmod(self.socket_path, 0o600)
            self.running = True
            self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._reader_thread = threading.Thread(target=self._read_pipe, daemon=True)
            self._server_thread.start()
            self._reader_thread.start()
        except Exception:
            self.running = False
            if self._server is not None:
                try: self._server.server_close()
                except Exception: pass
                try: os.unlink(self.socket_path)
                except OSError: pass
            for stream, fd in ((self._command, command_fd), (self._response, response_fd)):
                try:
                    if stream is not None: stream.close()
                    else: os.close(fd)
                except OSError:
                    pass
            raise

    @classmethod
    def launch(cls, chrome_binary, profile, socket_path, chrome_args=()):
        """Launch Chrome with fd 3/4 without a multithreaded preexec_fn.

        socket_path must have a short, private 0700 parent, typically mkdtemp.
        """
        _private_socket_path(socket_path)
        to_read, to_write = os.pipe()
        try:
            from_read, from_write = os.pipe()
        except Exception:
            os.close(to_read)
            os.close(to_write)
            raise
        wrapper = ("import fcntl,os,sys; a,b=map(int,sys.argv[1:3]); "
                   "x=fcntl.fcntl(a,fcntl.F_DUPFD,5); y=fcntl.fcntl(b,fcntl.F_DUPFD,5); "
                   "os.dup2(x,3); os.dup2(y,4); "
                   "os.set_inheritable(3,True); os.set_inheritable(4,True); "
                   "os.close(x); os.close(y); "
                   "os.close(a) if a not in (3,4) else None; "
                   "os.close(b) if b not in (3,4) else None; "
                   "os.execv(sys.argv[3],sys.argv[3:])")
        argv = [sys.executable, '-c', wrapper, str(to_read), str(from_write), str(chrome_binary),
                '--user-data-dir=' + str(profile), '--remote-debugging-pipe',
                '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
                '--disable-component-update', '--disable-sync', *chrome_args, 'about:blank']
        try:
            process = subprocess.Popen(argv, pass_fds=(to_read, from_write),
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, start_new_session=True)
        except Exception:
            for fd in (to_read, to_write, from_read, from_write):
                try: os.close(fd)
                except OSError: pass
            raise
        os.close(to_read)
        os.close(from_write)
        try:
            return cls(socket_path, to_write, from_read, process)
        except Exception:
            try:
                if process.poll() is None: process.terminate()
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                    process.wait(timeout=2)
                except Exception:
                    pass
            raise

    def _add(self, client):
        with self._lock:
            self._clients.add(client)

    def _init_root(self, client):
        with self._lock:
            self._counter += 1
            identifier = self._counter
            self._pending[identifier] = (client, None, '__root__')
        self._send_pipe({'id': identifier, 'method': 'Target.attachToBrowserTarget'})
        if not client.ready.wait(5) or not client.root_session:
            raise PipeError('Could not attach private browser session')

    def _send_pipe(self, message):
        payload = json.dumps(message, separators=(',', ':')).encode()
        with self._write_lock:
            self._command.write(payload + b'\0')

    def _remove(self, client):
        with self._lock:
            self._clients.discard(client)
            for session in client.sessions:
                self._sessions.pop(session, None)
            for key, pending in list(self._pending.items()):
                if pending[0] is client:
                    del self._pending[key]
            root = client.root_session
            if root and self.running:
                self._counter += 1
                detach_id = self._counter
            else:
                detach_id = None
        if detach_id is not None:
            try:
                self._send_pipe({'id': detach_id, 'method': 'Target.detachFromTarget',
                                 'params': {'sessionId': root}})
            except OSError:
                pass
        try:
            client.sock.close()
        except OSError:
            pass

    def _forward(self, client, message):
        if not isinstance(message, dict) or not isinstance(message.get('id'), int) or isinstance(message['id'], bool) or not isinstance(message.get('method'), str):
            raise PipeError('Invalid CDP command')
        if len(json.dumps(message).encode()) > MAX_MESSAGE:
            raise PipeError('CDP command too large')
        with self._lock:
            session = message.get('sessionId')
            if session is not None and self._sessions.get(session) is not client:
                client.send({'id': message['id'], 'error': {'message': 'Unknown CDP session'}})
                return
            self._counter += 1
            identifier = self._counter
            self._pending[identifier] = (client, message['id'], message['method'])
        forwarded = dict(message, id=identifier)
        if session is None and client.root_session:
            forwarded['sessionId'] = client.root_session
        self._send_pipe(forwarded)

    def _read_pipe(self):
        buffer = bytearray()
        try:
            while self.running:
                block = self._response.read(65536)
                if not block:
                    break
                buffer.extend(block)
                if len(buffer) > MAX_MESSAGE and b'\0' not in buffer:
                    break
                while b'\0' in buffer:
                    raw, _, remainder = buffer.partition(b'\0')
                    buffer = bytearray(remainder)
                    if len(raw) > MAX_MESSAGE:
                        raise PipeError('Chrome response too large')
                    try:
                        self._dispatch(json.loads(raw))
                    except (ValueError, UnicodeDecodeError):
                        raise PipeError('Invalid Chrome response') from None
        except (OSError, PipeError):
            pass
        finally:
            self.running = False
            with self._lock:
                clients = list(self._clients)
            for client in clients:
                try:
                    client.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def _dispatch(self, message):
        if not isinstance(message, dict):
            return
        if 'id' in message:
            with self._lock:
                pending = self._pending.pop(message['id'], None)
                if not pending:
                    return
                client, local_id, method = pending
                if client not in self._clients:
                    return
                if method == '__root__':
                    result = message.get('result')
                    session = result.get('sessionId') if isinstance(result, dict) else None
                    if isinstance(session, str):
                        client.root_session = session
                        self._sessions[session] = client
                        client.sessions.add(session)
                    client.ready.set()
                    return
                if method == 'Target.attachToTarget':
                    result = message.get('result')
                    session = result.get('sessionId') if isinstance(result, dict) else None
                    if isinstance(session, str):
                        self._sessions[session] = client
                        client.sessions.add(session)
                if method == 'Target.detachFromTarget':
                    # Chrome's detach event also clears the mapping.
                    pass
            message = dict(message, id=local_id)
            if message.get('sessionId') == client.root_session:
                message.pop('sessionId', None)
            try:
                client.send(message)
            except OSError:
                self._remove(client)
            return
        session = message.get('sessionId')
        with self._lock:
            if session:
                clients = [self._sessions[session]] if session in self._sessions else []
            else:
                # Only genuine browser-wide target discovery is shared.
                clients = list(self._clients) if message.get('method') in ('Target.targetCreated', 'Target.targetDestroyed', 'Target.targetInfoChanged') else []
        for client in clients:
            try:
                event = message
                if session and event.get('method') == 'Target.attachedToTarget':
                    child = event.get('params', {}).get('sessionId')
                    if isinstance(child, str):
                        with self._lock:
                            self._sessions[child] = client
                            client.sessions.add(child)
                elif session and event.get('method') == 'Target.detachedFromTarget':
                    child = event.get('params', {}).get('sessionId')
                    if isinstance(child, str):
                        with self._lock:
                            self._sessions.pop(child, None)
                            client.sessions.discard(child)
                if session == client.root_session:
                    event = dict(message)
                    event.pop('sessionId', None)
                client.send(event)
            except OSError:
                self._remove(client)

    def connect(self, target_id=None):
        client = PipeClient(self.socket_path)
        if target_id is None:
            return client
        try:
            client.attach(target_id)
            return client
        except Exception:
            client.close()
            raise

    def close(self):
        if self._server is None:
            return
        if self.running:
            try:
                with self.connect() as client:
                    client.call('Browser.close', timeout=2)
            except (PipeError, OSError, TimeoutError):
                pass
        self.running = False
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self.process is not None:
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
        try:
            self._command.close()
            self._response.close()
        except OSError:
            pass
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass


class PipeClient:
    def __init__(self, socket_path, timeout=5):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.sock.settimeout(timeout)
            self.sock.connect(str(socket_path))
        except OSError:
            self.sock.close()
            raise PipeError('Browser socket connection failed') from None
        self.counter = 0
        self.session_id = None
        key = base64.b64encode(os.urandom(16)).decode()
        request = ('GET /devtools/browser/pip HTTP/1.1\r\nHost: 127.0.0.1:9\r\n'
                   'Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: ' + key +
                   '\r\nSec-WebSocket-Version: 13\r\n\r\n')
        try:
            self.sock.sendall(request.encode())
            header = bytearray()
            while b'\r\n\r\n' not in header and len(header) < 16384:
                header.extend(_exact(self.sock, 1))
        except (OSError, EOFError):
            self.close()
            raise PipeError('Browser socket handshake failed') from None
        expect = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
        if b' 101 ' not in header.split(b'\r\n', 1)[0] or ('Sec-WebSocket-Accept: ' + expect).encode() not in header:
            self.close()
            raise PipeError('Browser socket handshake failed')

    def call(self, method, params=None, timeout=5):
        self.counter += 1
        identifier = self.counter
        command = {'id': identifier, 'method': method, 'params': params or {}}
        if self.session_id and method not in ('Target.detachFromTarget',):
            command['sessionId'] = self.session_id
        deadline = time.monotonic() + min(max(float(timeout), 0), 5)
        events = 0
        try:
            self.sock.sendall(_frame(json.dumps(command, separators=(',', ':')).encode(), mask=True))
            while True:
                if time.monotonic() >= deadline or events >= 256:
                    raise PipeError('Browser reply timed out')
                opcode, raw = _read_frame(self.sock, masked=False, deadline=deadline)
                if opcode == 8:
                    raise PipeError('Browser connection closed')
                if opcode == 9:
                    self.sock.sendall(_frame(raw, 10, mask=True))
                    continue
                if opcode != 1:
                    continue
                reply = json.loads(raw)
                if reply.get('id') != identifier:
                    events += 1
                    continue
                if 'error' in reply:
                    raise PipeError(reply['error'].get('message', 'CDP error'))
                return reply.get('result', {})
        except (OSError, EOFError, ValueError, TimeoutError):
            raise PipeError('Browser connection failed') from None

    def attach(self, target_id):
        result = self.call('Target.attachToTarget', {'targetId': target_id, 'flatten': True})
        self.session_id = result['sessionId']
        return self

    def session(self, target_id):
        return self.attach(target_id)

    def close(self):
        if self.session_id:
            try:
                self.call('Target.detachFromTarget', {'sessionId': self.session_id}, timeout=1)
            except (OSError, PipeError, TimeoutError):
                pass
            self.session_id = None
        self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
