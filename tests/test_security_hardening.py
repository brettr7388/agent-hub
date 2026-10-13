"""Security controls tested without listening sockets or Tailscale changes."""

import hashlib
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import sqlite3
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hub_security as security
import hub
from tests import test_hub as hub_tests

SCRATCH = Path(__file__).resolve().parents[1] / 'data' / 'test-runs'


class HeaderDeadlineTests(unittest.TestCase):
    def test_slow_drip_inside_one_header_line_is_stopped(self):
        stopped = threading.Event()
        class Connection:
            def settimeout(self, seconds):
                pass
            def shutdown(self, how):
                stopped.set()
        class DrippingReader:
            def readline(self, *args):
                stopped.wait(1)
                return b''
        class Parent:
            def handle_one_request(self):
                self.rfile.readline()
        class Handler(security.HeaderDeadlineMixin, Parent):
            pass
        handler = Handler()
        handler.rfile = DrippingReader()
        handler.connection = Connection()
        with patch.object(security, 'HEADER_SECONDS', .02):
            handler.handle_one_request()
        self.assertTrue(stopped.is_set())

    def test_total_deadline_across_reads(self):
        connection = Mock()
        reader = security.DeadlineReader(io.BytesIO(b'GET / HTTP/1.1\r\nHost: x\r\n'), connection, 10)
        with patch.object(security.time, 'monotonic', side_effect=[1, 9.9, 10.01]):
            self.assertTrue(reader.readline().startswith(b'GET'))
            self.assertTrue(reader.readline().startswith(b'Host'))
            with self.assertRaises(socket.timeout):
                reader.readline()
        self.assertAlmostEqual(connection.settimeout.call_args_list[0].args[0], 9)
        self.assertAlmostEqual(connection.settimeout.call_args_list[1].args[0], .1)

    def test_deadline_cleared_for_body(self):
        connection = Mock()
        reader = security.DeadlineReader(io.BytesIO(b'body'), connection, 0)
        reader.deadline = None
        self.assertEqual(reader.read(4), b'body')
        connection.settimeout.assert_not_called()


class HandlerLimitTests(unittest.TestCase):
    def test_full_server_rejects_before_spawning_thread(self):
        server = security.BoundedThreadingHTTPServer.__new__(security.BoundedThreadingHTTPServer)
        server._handler_slots = threading.BoundedSemaphore(1)
        self.assertTrue(server._handler_slots.acquire(False))
        server.shutdown_request = Mock()
        try:
            server.process_request(object(), ('127.0.0.1', 1))
        finally:
            server._handler_slots.release()
        server.shutdown_request.assert_called_once()


class UploadQuotaTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='security-', dir=str(SCRATCH))
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.uploads = root / 'uploads'
        self.uploads.mkdir()
        self.db = sqlite3.connect(':memory:', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE messages(uploads TEXT,text TEXT,cards TEXT)')
        self.db.execute('CREATE TABLE jobs(prompt TEXT)')
        self.hub = type('Hub', (), {})()
        self.hub.uploads = self.uploads
        self.hub.db = self.db
        self.hub.lock = threading.RLock()
        self.hub.config = {'max_total_upload_bytes': 100}
        self.quota = security.UploadQuota(self.hub)

    def test_reservations_do_not_overcommit_under_concurrency(self):
        entered = threading.Event()
        release = threading.Event()
        result = []

        def first():
            with self.quota.reserve(self.uploads / 'first', 70):
                entered.set()
                release.wait(2)

        t = threading.Thread(target=first)
        t.start()
        self.assertTrue(entered.wait(2))
        try:
            with self.assertRaises(Exception) as raised:
                with self.quota.reserve(self.uploads / 'second', 40):
                    pass
            self.assertEqual(raised.exception.status, 413)
        finally:
            release.set()
            t.join(2)
        self.assertFalse(t.is_alive())

    def test_cleanup_preserves_references_and_inflight(self):
        old = time.time() - 2 * security.UPLOAD_RETENTION_SECONDS
        attachment = self.uploads / 'attachment'
        prose = self.uploads / 'prose with spaces'
        orphan = self.uploads / ('a' * 24 + '-orphan')
        in_flight = self.uploads / 'in_flight'
        for path in (attachment, prose, orphan, in_flight):
            path.write_bytes(b'abc')
            os.utime(path, (old, old))
        self.db.execute('INSERT INTO messages VALUES(?,?,?)',
                        (json.dumps([str(attachment)]), 'see ' + str(prose), '[]'))
        self.db.commit()
        # An in-flight file is tracked by its reservation path.
        self.quota.pending[in_flight] = 3
        try:
            with self.hub.lock:
                self.assertEqual(self.quota.cleanup(), 1)
        finally:
            del self.quota.pending[in_flight]
        self.assertTrue(attachment.exists())
        self.assertTrue(prose.exists())
        self.assertTrue(in_flight.exists())
        self.assertFalse(orphan.exists())

    def test_existing_disk_and_pending_count_once(self):
        p = self.uploads / 'first'
        with self.quota.reserve(p, 70):
            p.write_bytes(b'x' * 70)
            with self.quota.reserve(self.uploads / 'second', 30):
                pass
        with self.assertRaises(Exception) as raised:
            with self.quota.reserve(self.uploads / 'third', 31):
                pass
        self.assertEqual(raised.exception.status, 413)


class LoginLimiterTests(unittest.TestCase):
    def test_shared_proxy_cannot_lock_out_owner(self):
        limiter = security.LoginLimiter()
        owner = hashlib.sha256(b'owner-token').hexdigest()
        for i in range(120):
            limiter.check('bad-%s' % i, owner, now=1)
        self.assertEqual(limiter.check('owner-token', owner, now=1), (True, 0))
        self.assertGreater(limiter.check('new-bad', owner, now=1)[1], 0)

    def test_token_backoff_expires_and_memory_is_bounded(self):
        limiter = security.LoginLimiter()
        owner = hashlib.sha256(b'owner').hexdigest()
        for i in range(11):
            valid, retry = limiter.check('bad', owner, now=1)
        self.assertFalse(valid)
        self.assertGreater(retry, 0)
        for i in range(1000):
            limiter.check('guess-%d' % i, owner, now=2)
        self.assertLessEqual(len(limiter.failures), security.LOGIN_MAX_KEYS)
        self.assertLessEqual(len(limiter.recent), security.LOGIN_GLOBAL_FAILURES + 1)
        self.assertEqual(limiter.check('bad', owner, now=62), (False, 0))


class TailscalePlanTests(unittest.TestCase):
    def test_exact_command_and_origin_from_local_status(self):
        cfg = {'bind': '127.0.0.1', 'port': 4700, 'allowed_origins': []}
        status = {'BackendState': 'Running', 'Self': {'DNSName': 'mac.tailnet.ts.net.'}}
        plan = security.tailscale_serve_plan(cfg, status)
        self.assertEqual(plan['origin'], 'https://mac.tailnet.ts.net')
        self.assertEqual(plan['command'], ['tailscale', 'serve', '--bg', 'http://127.0.0.1:4700'])
        self.assertEqual(plan['allowed_origins'], ['https://mac.tailnet.ts.net'])
        self.assertEqual(cfg['allowed_origins'], [])
        with self.assertRaises(ValueError):
            security.tailscale_serve_plan(dict(cfg, bind='0.0.0.0'), status)

    def test_status_is_local_read_only_subprocess(self):
        run = Mock(return_value=type('Result', (), {'stdout': '{"BackendState":"Running"}'})())
        self.assertEqual(security.local_tailscale_status(run)['BackendState'], 'Running')
        run.assert_called_once_with(['tailscale', 'status', '--json'],
                                    text=True, timeout=5, check=True)

    def test_main_preview_saves_origin_without_running_serve(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='security-', dir=str(SCRATCH)) as scratch:
            root = Path(scratch)
            (root / 'config.json').write_text(json.dumps({'bind': '127.0.0.1', 'port': 4700,
                                                         'allowed_origins': []}))
            status = {'BackendState': 'Running', 'Self': {'DNSName': 'mac.tailnet.ts.net.'}}
            output = io.StringIO()
            with patch.object(hub, 'ROOT', root), patch.object(hub, 'local_tailscale_status',
                                                               return_value=status) as local, \
                    patch.object(sys, 'argv', ['hub.py', '--tailscale']), redirect_stdout(output):
                hub.main()
            local.assert_called_once_with()
            saved = json.loads((root / 'config.json').read_text())
            self.assertEqual(saved['allowed_origins'], ['https://mac.tailnet.ts.net'])
            self.assertIn('tailscale serve --bg http://127.0.0.1:4700', output.getvalue())


class HandlerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.case = hub_tests.HubCase()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_valid_owner_login_after_shared_proxy_failures(self):
        for i in range(120):
            status, _, _ = self.case.request('/api/login', 'POST', {'token': 'wrong-%s' % i})
            self.assertIn(status, (401, 429))
        status, _, body = self.case.request('/api/login', 'POST',
                                            {'token': self.case.h.initial_token})
        self.assertEqual(status, 200, body)

    def test_handler_upload_applies_aggregate_quota_before_body(self):
        self.case.h.config['max_total_upload_bytes'] = 12
        self.case.cookie = self.case.login()
        headers = {'Content-Type': 'application/octet-stream'}
        status, _, body = self.case.api('/api/upload?name=first.bin', 'POST', b'12345678',
                                        headers=headers, raw=True)
        self.assertEqual(status, 200, body)
        status, _, body = self.case.api('/api/upload?name=second.bin', 'POST', b'abcdefgh',
                                        headers=headers, raw=True)
        self.assertEqual(status, 413, body)
        self.assertEqual(sum(p.stat().st_size for p in self.case.h.uploads.iterdir()), 8)


if __name__ == '__main__':
    unittest.main()
