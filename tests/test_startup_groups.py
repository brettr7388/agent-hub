"""Startup and group naming checks with temporary data and fake socket binding."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hub

TEST_RUNS = hub.ROOT / 'data' / 'test-runs'


class StartupCase(unittest.TestCase):
    def setUp(self):
        TEST_RUNS.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=str(TEST_RUNS))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'agents').mkdir()
        config = hub.read_json(hub.ROOT / 'config.example.json', {})
        config['detect_engines'] = False
        (self.root / 'config.example.json').write_text(json.dumps(config))
        (self.root / 'config.json').write_text(json.dumps(config))

    def start(self, bind, *args):
        output = io.StringIO()
        with (mock.patch.object(hub, 'ROOT', self.root),
              mock.patch.object(hub, 'Server', side_effect=bind),
              mock.patch.object(hub.Hub, 'start_scheduler'),
              mock.patch.object(hub.signal, 'signal'),
              mock.patch.object(sys, 'argv', ['hub.py', *args]),
              contextlib.redirect_stdout(output)):
            hub.main()
        return output.getvalue()

    def test_busy_first_port_does_not_consume_token(self):
        with self.assertRaises(SystemExit) as error:
            self.start(OSError(98, 'Address already in use'), '--reset-token')
        self.assertIn('port 4700', str(error.exception))
        self.assertIn('nano config.json', str(error.exception))
        self.assertFalse((self.root / 'data' / 'auth.json').exists())

        test_case = self
        expect_empty = True
        class FakeServer:
            server_address = ('127.0.0.1', 4700)
            def __init__(self, address, instance):
                if expect_empty:
                    test_case.assertFalse((test_case.root / 'data' / 'auth.json').exists())
            def serve_forever(self): pass
            def server_close(self): pass

        output = self.start(FakeServer)
        self.assertIn('Login token (shown once; save it): ', output)
        saved = json.loads((self.root / 'data' / 'auth.json').read_text())
        self.assertTrue(saved['token_hash'])
        expect_empty = False
        self.assertNotIn('Login token', self.start(FakeServer))
        self.assertEqual(saved, json.loads((self.root / 'data' / 'auth.json').read_text()))

    def test_busy_port_does_not_reset_existing_token(self):
        class FakeServer:
            server_address = ('127.0.0.1', 4700)
            def __init__(self, address, instance): pass
            def serve_forever(self): pass
            def server_close(self): pass

        self.start(FakeServer)
        auth = self.root / 'data' / 'auth.json'
        before = auth.read_bytes()
        with self.assertRaises(SystemExit):
            self.start(OSError(98, 'Address already in use'), '--reset-token')
        self.assertEqual(before, auth.read_bytes())
        self.assertIn('Login token', self.start(FakeServer, '--reset-token'))
        self.assertNotEqual(before, auth.read_bytes())


class GroupCase(unittest.TestCase):
    def test_default_name_can_be_renamed(self):
        TEST_RUNS.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(TEST_RUNS)) as directory:
            root = Path(directory)
            (root / 'agents' / 'ada').mkdir(parents=True)
            (root / 'agents' / 'ada' / 'CLAUDE.md').write_text('# Ada\n')
            (root / 'agents' / 'bea').mkdir()
            (root / 'agents' / 'bea' / 'CLAUDE.md').write_text('# Bea\n')
            config = hub.read_json(hub.ROOT / 'config.example.json', {})
            config.update(agents_dir='agents', detect_engines=False)
            instance = hub.Hub(root, config)
            try:
                members = ['ada', 'bea']
                self.assertEqual(set(instance.agents()), {'ada', 'bea', 'guide'})
                chat = instance.group({'agents': members})['chat']
                self.assertEqual(chat['name'], 'Ada & Bea')
                renamed = instance.rename_group({'id': chat['id'], 'name': 'Research'})['chat']
                self.assertEqual(renamed['name'], 'Research')
                self.assertEqual(instance.chat(chat['id'])['name'], 'Research')
                with self.assertRaises(hub.HubError):
                    instance.rename_group({'id': chat['id'], 'name': ''})
                with self.assertRaises(hub.HubError) as invalid:
                    instance.rename_group({'id': ['bad'], 'name': 'Oops'})
                self.assertEqual(invalid.exception.status, 400)
                with instance.lock:
                    instance.db.execute("INSERT INTO archives(kind,id) VALUES('chat',?)", (chat['id'],))
                    instance.db.commit()
                with self.assertRaises(hub.HubError) as archived:
                    instance.rename_group({'id': chat['id'], 'name': 'Oops'})
                self.assertEqual(archived.exception.status, 404)
                with instance.lock:
                    saved = instance.db.execute('SELECT name FROM chats WHERE id=?', (chat['id'],)).fetchone()['name']
                self.assertEqual(saved, 'Research')
            finally:
                instance.close()

    def test_scratch_team_workers_get_distinct_angles(self):
        TEST_RUNS.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(TEST_RUNS)) as directory:
            root = Path(directory)
            (root / 'agents').mkdir()
            config = hub.read_json(hub.ROOT / 'config.example.json', {})
            config.update(agents_dir='agents', detect_engines=False,
                          claude_bin=str(Path(__file__).with_name('fake_claude.py')))
            instance = hub.Hub(root, config)
            try:
                with (mock.patch.object(instance, 'send', return_value={'job_id': 1}),
                      mock.patch.object(instance, 'swarm_job_finished')):
                    team = instance.create_swarm({'goal': 'Each give one octopus fact',
                        'shape': 'partition', 'count': 2})
                slices = [worker['slice'] for worker in team['workers']]
                self.assertEqual(len(set(slices)), 2)
                self.assertIn('physical traits or components', slices[0])
                self.assertIn('behavior or actions', slices[1])
                self.assertTrue(all('Each give one octopus fact' in item for item in slices))
            finally:
                instance.close()


if __name__ == '__main__': unittest.main()
