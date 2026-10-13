"""PASS12 security regressions using local files and fake readers only."""
import io
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

import hub_security as security
import hub_export
import hub
from hub import HubError
import test_hub


class SecurityHelpers(unittest.TestCase):
    def test_authenticated_cookie_uses_reserved_handler_slot(self):
        server = security.BoundedThreadingHTTPServer.__new__(security.BoundedThreadingHTTPServer)
        server._handler_slots = threading.BoundedSemaphore(3)
        server._admission_lock = threading.Lock()
        server._admitted = {}
        server._unauth_by_ip = {}
        server._unauth_total = 0
        server._unauth_limit = 1
        server._max_unauth_per_ip = 1
        server.hub = Mock()
        server.hub.authenticated.side_effect = lambda token: token == 'valid'
        server.shutdown_request = Mock()
        slow = Mock()
        slow.recv.return_value = b''
        owner = Mock()
        owner.recv.return_value = b'GET /api/state HTTP/1.1\r\nCookie: hub_session=valid\r\n\r\n'
        with patch.object(security.ThreadingHTTPServer, 'process_request') as spawned:
            server.process_request(slow, ('127.0.0.1', 1))
            server.process_request(owner, ('127.0.0.1', 2))
            self.assertEqual(spawned.call_count, 2)
            self.assertEqual(server._unauth_total, 1)
            rejected = Mock(); rejected.recv.return_value = b''
            server.process_request(rejected, ('127.0.0.1', 3))
            server.shutdown_request.assert_called_once()
        server._release_admission(slow)
        server._release_admission(owner)
        server._handler_slots.release()
        server._handler_slots.release()

    def test_environment_is_allowlisted(self):
        result = security.allowed_agent_environment({
            'PATH': '/bin', 'HOME': '/tmp/user', 'LANG': 'en_US.UTF-8',
            'LC_ALL': 'C', 'ANTHROPIC_API_KEY': 'fake', 'OPENAI_API_KEY': 'fake',
            'AWS_SECRET_ACCESS_KEY': 'must-drop', 'GITHUB_TOKEN': 'must-drop',
            'CUSTOM_SECRET': 'must-drop'})
        self.assertEqual(set(result), {'PATH', 'HOME', 'LANG', 'LC_ALL',
                                       'ANTHROPIC_API_KEY', 'OPENAI_API_KEY'})

    def test_workdir_stays_in_home_and_out_of_private_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / 'home'; home.mkdir()
            project = home / 'projects' / 'demo'; project.mkdir(parents=True)
            private = home / '.ssh'; private.mkdir()
            private_upper = home / '.SSH'; private_upper.mkdir(exist_ok=True)
            link = project / 'secret'; link.symlink_to(private)
            self.assertEqual(security.validate_safe_workdir(project, home), project.resolve())
            self.assertEqual(security.validate_safe_workdir(home, home), home.resolve())
            for path in (private, private_upper, link, Path(folder)):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    security.validate_safe_workdir(path, home)

    def test_opened_file_cannot_follow_replaced_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve() / 'allowed'; root.mkdir()
            outside = Path(folder) / 'outside'; outside.write_text('secret')
            target = root / 'file.txt'; target.write_text('safe')
            with security.open_validated_file(target, [root]) as stream:
                self.assertEqual(stream.read(), b'safe')
            target.unlink(); target.symlink_to(outside)
            with self.assertRaises(HubError) as got:
                with security.open_validated_file(target, [root]):
                    pass
            self.assertEqual(got.exception.status, 403)

    def test_body_deadline_and_early_eof(self):
        connection = Mock()
        self.assertEqual(security.read_body_with_deadline(io.BytesIO(b'body'), connection, 4), b'body')
        with self.assertRaises(EOFError):
            security.read_body_with_deadline(io.BytesIO(b'x'), connection, 2)
        stopped = threading.Event()
        class SlowReader:
            def read(self, amount):
                stopped.wait(1)
                return b''
        connection.shutdown.side_effect = lambda how: stopped.set()
        with self.assertRaises(socket.timeout):
            security.read_body_with_deadline(SlowReader(), connection, 1, .02)

    def test_client_disconnect_does_not_log_server_traceback(self):
        server = security.BoundedThreadingHTTPServer.__new__(security.BoundedThreadingHTTPServer)
        with patch.object(security.ThreadingHTTPServer, 'handle_error') as logged:
            try:
                raise ConnectionResetError('browser closed')
            except ConnectionResetError:
                server.handle_error(None, ('127.0.0.1', 1))
        logged.assert_not_called()


class ExportSecurity(unittest.TestCase):
    setUp = test_hub.HubCase.setUp

    def test_instruction_secret_redacted_and_auth_never_added(self):
        agent = self.root / 'agents' / 'assistant'
        (agent / 'NOTES.md').write_text('password=example-secret\n')
        (agent / 'CLAUDE.md').write_text('Help with planning.\napi_key=another-example-secret\n')
        (agent / 'auth.json').write_text('{"token":"example-secret"}')
        with zipfile.ZipFile(io.BytesIO(hub_export.everything(self.h))) as archive:
            names = set(archive.namelist())
            self.assertIn('agents/assistant/CLAUDE.md', names)
            self.assertIn('agents/assistant/NOTES.md', names)
            self.assertNotIn('agents/assistant/auth.json', names)
            readme = archive.read('README.md').decode()
            self.assertIn('Redactions:', readme)
            self.assertIn('[redacted]', archive.read('agents/assistant/NOTES.md').decode())
            self.assertIn('[redacted]', archive.read('agents/assistant/CLAUDE.md').decode())
            self.assertNotIn('example-secret', b''.join(archive.read(n) for n in names).decode())

    def test_upload_timeout_releases_quota_and_removes_partial_file(self):
        stopped = threading.Event()
        class SlowReader:
            def read(self, amount):
                stopped.wait(1)
                return b''
        class Connection:
            def settimeout(self, seconds):
                pass
            def shutdown(self, how):
                stopped.set()
        handler = Mock()
        handler.hub = self.h
        handler.headers = {'Content-Length': '3'}
        handler.rfile = SlowReader()
        handler.connection = Connection()
        before = set(self.h.uploads.iterdir())
        with patch.object(hub, 'upload_deadline_seconds', return_value=.02):
            with self.assertRaises(socket.timeout):
                hub.Handler.upload(handler, {'name': ['slow.bin']})
        self.assertEqual(self.h.upload_quota.pending, {})
        self.assertEqual(set(self.h.uploads.iterdir()), before)

    def test_explicit_context_skips_symlinked_instruction_file(self):
        folder = self.root / 'agents' / 'assistant'
        private = self.root / 'private-note.txt'
        private.write_text('private sentinel')
        (folder / 'NOTES.md').unlink(missing_ok=True)
        (folder / 'NOTES.md').symlink_to(private)
        context = self.h.explicit_agent_context({'path': str(folder)})
        self.assertNotIn('private sentinel', context)
        self.assertIn('CLAUDE.md', context)


if __name__ == '__main__':
    unittest.main()
