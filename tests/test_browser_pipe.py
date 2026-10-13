"""Pipe broker tests use a fake Chrome pipe and mocked Unix server."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from hub_browser_pipe import PipeBroker, PipeClient, PipeError, _private_socket_path


class FakeServer:
    def __init__(self, path, handler):
        self.path = path
        Path(path).touch()
    def serve_forever(self):
        pass
    def shutdown(self):
        pass
    def server_close(self):
        pass


class FakePeer:
    def __init__(self):
        self.messages = []
        self.sessions = set()
        self.root_session = None
        self.ready = threading.Event()
        self.sock = mock.Mock()
    def send(self, message):
        self.messages.append(message)


class PipeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='pip-cdp-', dir=str(Path('/tmp').resolve()))
        os.chmod(self.tmp.name, 0o700)
        self.path = Path(self.tmp.name) / 'browser.sock'
        self.command_read, command_write = os.pipe()
        response_read, self.response_write = os.pipe()
        self.patch = mock.patch('hub_browser_pipe._UnixServer', FakeServer)
        self.patch.start()
        self.broker = PipeBroker(self.path, command_write, response_read)

    def tearDown(self):
        os.close(self.response_write)
        self.broker.close()
        self.patch.stop()
        for fd in (self.command_read,):
            try: os.close(fd)
            except OSError: pass
        self.tmp.cleanup()

    def chrome_command(self):
        raw = bytearray()
        while b'\0' not in raw:
            raw.extend(os.read(self.command_read, 8192))
        return json.loads(raw.split(b'\0')[0])

    def test_command_ids_remapped_for_two_clients(self):
        a, b = FakePeer(), FakePeer()
        self.broker._add(a); self.broker._add(b)
        self.broker._forward(a, {'id': 1, 'method': 'Browser.getVersion'})
        first = self.chrome_command()
        self.broker._forward(b, {'id': 1, 'method': 'Target.getTargets'})
        second = self.chrome_command()
        self.assertNotEqual(first['id'], second['id'])
        self.broker._dispatch({'id': second['id'], 'result': {'targets': []}})
        self.broker._dispatch({'id': first['id'], 'result': {'version': 'fake'}})
        self.assertEqual(a.messages, [{'id': 1, 'result': {'version': 'fake'}}])
        self.assertEqual(b.messages, [{'id': 1, 'result': {'targets': []}}])

    def test_flattened_session_ownership_and_events(self):
        a, b = FakePeer(), FakePeer()
        self.broker._add(a); self.broker._add(b)
        self.broker._forward(a, {'id': 7, 'method': 'Target.attachToTarget', 'params': {'targetId': 'page', 'flatten': True}})
        command = self.chrome_command()
        self.broker._dispatch({'id': command['id'], 'result': {'sessionId': 'private-session'}})
        self.assertEqual(a.messages[-1]['id'], 7)
        self.broker._forward(b, {'id': 7, 'method': 'Runtime.evaluate', 'sessionId': 'private-session'})
        self.assertEqual(b.messages[-1]['error']['message'], 'Unknown CDP session')
        self.broker._dispatch({'method': 'Runtime.consoleAPICalled', 'sessionId': 'private-session', 'params': {}})
        self.assertEqual(a.messages[-1]['method'], 'Runtime.consoleAPICalled')
        self.assertNotIn('method', b.messages[-1])
        self.broker._forward(a, {'id': 8, 'method': 'Runtime.evaluate', 'sessionId': 'private-session'})
        self.assertEqual(self.chrome_command()['sessionId'], 'private-session')

    def test_browser_events_broadcast(self):
        a, b = FakePeer(), FakePeer()
        self.broker._add(a); self.broker._add(b)
        event = {'method': 'Target.targetCreated', 'params': {'targetInfo': {'targetId': 'x'}}}
        self.broker._dispatch(event)
        self.assertEqual(a.messages, [event])
        self.assertEqual(b.messages, [event])

    def test_private_browser_roots_and_nested_auto_attach(self):
        a, b = FakePeer(), FakePeer()
        self.broker._add(a); self.broker._add(b)
        def establish(client, session):
            worker = threading.Thread(target=lambda: self.broker._init_root(client))
            worker.start()
            command = self.chrome_command()
            self.assertEqual(command['method'], 'Target.attachToBrowserTarget')
            self.broker._dispatch({'id': command['id'], 'result': {'sessionId': session}})
            worker.join(1)
            self.assertFalse(worker.is_alive())
        establish(a, 'root-a'); establish(b, 'root-b')
        self.broker._forward(a, {'id': 1, 'method': 'Target.setAutoAttach', 'params': {'autoAttach': True, 'flatten': True}})
        self.assertEqual(self.chrome_command()['sessionId'], 'root-a')
        self.broker._forward(b, {'id': 1, 'method': 'Target.setAutoAttach', 'params': {'autoAttach': True, 'flatten': True}})
        self.assertEqual(self.chrome_command()['sessionId'], 'root-b')
        self.broker._dispatch({'method': 'Target.attachedToTarget', 'sessionId': 'root-a',
                               'params': {'sessionId': 'child-a', 'targetInfo': {'targetId': 'page'}}})
        self.assertIn('child-a', a.sessions)
        self.assertEqual(a.messages[-1]['params']['sessionId'], 'child-a')
        self.assertNotIn('sessionId', a.messages[-1])
        self.assertFalse(b.messages)
        self.broker._remove(a)
        detach = self.chrome_command()
        self.assertEqual(detach['method'], 'Target.detachFromTarget')
        self.assertEqual(detach['params']['sessionId'], 'root-a')

    def test_socket_path_requires_private_unused_directory(self):
        fresh = Path(self.tmp.name) / 'fresh.sock'
        self.assertEqual(_private_socket_path(fresh), fresh)
        with tempfile.TemporaryDirectory() as folder:
            os.chmod(folder, 0o755)
            with self.assertRaises(PipeError): _private_socket_path(Path(folder) / 'socket')
        fresh.symlink_to('/tmp/untrusted')
        with self.assertRaises(PipeError): _private_socket_path(fresh)
        fresh.unlink()
        with mock.patch('hub_browser_pipe.os.getuid', return_value=os.getuid() + 1):
            with self.assertRaisesRegex(PipeError, 'owned by this user'):
                _private_socket_path(fresh)

    def test_server_failure_closes_fds_and_reaps_launched_child(self):
        class FakeProcess:
            def __init__(self): self.terminated = False; self.waited = False
            def poll(self): return None
            def terminate(self): self.terminated = True
            def wait(self, timeout=None): self.waited = True; return 0
        process = FakeProcess()
        fds = []
        real_pipe = os.pipe
        def tracked_pipe():
            pair = real_pipe(); fds.extend(pair); return pair
        with mock.patch('hub_browser_pipe.os.pipe', side_effect=tracked_pipe), \
             mock.patch('hub_browser_pipe.subprocess.Popen', return_value=process), \
             mock.patch('hub_browser_pipe._UnixServer', side_effect=OSError('bind failed')):
            with self.assertRaisesRegex(OSError, 'bind failed'):
                PipeBroker.launch('/fake/chrome', self.tmp.name, Path(self.tmp.name) / 'failed.sock')
        self.assertTrue(process.terminated)
        self.assertTrue(process.waited)
        for fd in fds:
            with self.assertRaises(OSError): os.fstat(fd)

    def test_constructor_path_rejection_closes_transferred_fds(self):
        command_read, command_write = os.pipe()
        response_read, response_write = os.pipe()
        try:
            with self.assertRaisesRegex(PipeError, 'already exists'):
                PipeBroker(self.path, command_write, response_read)
            for fd in (command_write, response_read):
                with self.assertRaises(OSError): os.fstat(fd)
        finally:
            os.close(command_read)
            os.close(response_write)

    def test_connector_call_has_finite_event_budget(self):
        client = PipeClient.__new__(PipeClient)
        client.sock = mock.Mock()
        client.counter = 0
        client.session_id = None
        event = (1, json.dumps({'method': 'Runtime.consoleAPICalled'}).encode())
        with mock.patch('hub_browser_pipe._read_frame', return_value=event) as read:
            with self.assertRaisesRegex(PipeError, 'timed out'):
                client.call('Runtime.evaluate')
        self.assertEqual(read.call_count, 256)

    def test_connector_call_uses_absolute_deadline(self):
        client = PipeClient.__new__(PipeClient)
        client.sock = mock.Mock()
        client.counter = 0
        client.session_id = None
        event = (1, json.dumps({'method': 'Runtime.consoleAPICalled'}).encode())
        ticks = iter(range(20))
        with mock.patch('hub_browser_pipe.time.monotonic', side_effect=lambda: next(ticks)), \
             mock.patch('hub_browser_pipe._read_frame', return_value=event) as read:
            with self.assertRaisesRegex(PipeError, 'timed out'):
                client.call('Runtime.evaluate', timeout=5)
        self.assertLess(read.call_count, 256)

    def test_launch_maps_chrome_pipe_descriptors(self):
        script = Path(self.tmp.name) / 'fake-chrome'
        script.write_text('#!' + os.path.realpath(__import__('sys').executable) + '\n'
                          'import json,os\n'
                          'raw=bytearray()\n'
                          'while not raw.endswith(b"\\0"): raw.extend(os.read(3,1))\n'
                          'cmd=json.loads(raw[:-1])\n'
                          'os.write(4,json.dumps({"id":cmd["id"],"result":{"pipe":True}}).encode()+b"\\0")\n')
        script.chmod(0o700)
        other = Path(self.tmp.name) / 'launched.sock'
        broker = PipeBroker.launch(script, Path(self.tmp.name) / 'profile', other)
        peer = FakePeer()
        broker._add(peer)
        broker._forward(peer, {'id': 42, 'method': 'Browser.getVersion'})
        until = time.monotonic() + 2
        while not peer.messages and time.monotonic() < until:
            time.sleep(0.01)
        self.assertEqual(peer.messages, [{'id': 42, 'result': {'pipe': True}}])
        broker.close()
        broker.close()


if __name__ == '__main__':
    unittest.main()
