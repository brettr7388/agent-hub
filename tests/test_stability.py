import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import hub
import test_hub


class StabilityCase(unittest.TestCase):
    setUp = test_hub.HubCase.setUp
    request = test_hub.HubCase.request
    login = test_hub.HubCase.login

    def test_restart_login_and_session_survive_without_reset(self):
        token = self.h.initial_token
        cookie = self.login()
        auth = self.h.auth_path.read_bytes()
        self.h.close()
        self.h = hub.Hub(self.root, self.h.config)
        self.addCleanup(self.h.close)
        self.assertIsNone(self.h.initial_token)
        self.assertEqual(auth, self.h.auth_path.read_bytes())
        self.assertTrue(self.h.authenticated(cookie))
        self.assertEqual(self.request('/api/login', 'POST', {'token': token})[0], 200)

    def test_login_error_logs_cause_without_token(self):
        token = self.h.initial_token
        with mock.patch.object(self.h.db, 'commit', side_effect=RuntimeError('fixture failure')):
            with self.assertLogs(level='ERROR') as logs:
                code, _, _ = self.request('/api/login', 'POST', {'token': token})
        self.assertEqual(code, 500)
        self.assertIn('RuntimeError: fixture failure', '\n'.join(logs.output))
        self.assertNotIn(token, '\n'.join(logs.output))

    def test_cursor_snapshot_and_sqlite_settings(self):
        self.h.sync_chats()
        result = self.h.db.execute('SELECT id FROM chats')
        # No SQLite cursor survives the execute call or a concurrent commit.
        self.h.db.execute('SELECT 1')
        self.h.db.commit()
        self.assertTrue(result.fetchall())
        self.assertEqual(self.h.db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
        self.assertEqual(self.h.db.execute('PRAGMA busy_timeout').fetchone()[0], 15000)


class StressCase(unittest.TestCase):
    def test_twenty_threads_for_sixty_seconds(self):
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('stress_worker.py'))],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-6000:])
        summary = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(summary['threads'], 20)
        self.assertGreaterEqual(summary['seconds'], 60)
        self.assertEqual(summary['integrity'], 'ok')
        print('Stress:', json.dumps(summary), flush=True)
