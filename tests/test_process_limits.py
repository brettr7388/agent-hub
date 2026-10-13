"""Real child pipes for bounded CLI and streamed agent supervision."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from hub_conversation import cli_choice
from hub_isolation import IsolationMixin
from hub_onboarding import _run_bounded
from hub_process import OutputLimitExceeded, run_bounded, start_process
from hub_stream import collect_output


class ProcessLimitsCase(unittest.TestCase):
    def overflowing_cli(self, directory, descriptor=1):
        path = Path(directory) / 'overflow-cli'
        path.write_text('#!' + sys.executable + '\nimport os,time\nos.write(%s,b"x"*131072)\ntime.sleep(30)\n' % descriptor)
        path.chmod(0o700)
        return str(path)

    def test_stdout_and_stderr_are_capped_while_child_writes(self):
        for stream in ('stdout', 'stderr'):
            with self.subTest(stream=stream):
                script = ('import os,sys,time; '
                          'os.write(sys.%s.fileno(), b"x" * 131072); time.sleep(30)' % stream)
                start = time.monotonic()
                with self.assertRaisesRegex(OutputLimitExceeded, stream):
                    run_bounded([sys.executable, '-c', script], timeout=3,
                                stdout_limit=1024, stderr_limit=1024)
                self.assertLess(time.monotonic() - start, 3)

    def test_onboarding_caps_both_pipes_before_child_finishes(self):
        for descriptor, stream in ((1, 'stdout'), (2, 'stderr')):
            with self.subTest(stream=stream), self.assertRaisesRegex(OutputLimitExceeded, stream):
                _run_bounded([sys.executable, '-c',
                              'import os,time; os.write(%s,b"x"*131072); time.sleep(30)' % descriptor],
                             Path.cwd(), os.environ.copy())

    def test_streamed_agent_caps_both_pipes(self):
        for stream in ('stdout', 'stderr'):
            with self.subTest(stream=stream):
                proc = start_process([sys.executable, '-c',
                    'import os,sys,time; os.write(sys.%s.fileno(), b"x"*10485760); time.sleep(30)' % stream],
                    text=True)
                with self.assertRaisesRegex(OutputLimitExceeded, stream):
                    collect_output(proc, 3, 'claude', lambda value: None)
                self.assertIsNotNone(proc.poll())

    @unittest.skipUnless(hasattr(os, 'fork'), 'requires Unix process groups')
    def test_descendant_holding_pipe_obeys_deadline(self):
        # The direct child exits, but its descendant retains both pipe writers.
        script = ('import os,time; pid=os.fork(); '
                  'time.sleep(30) if pid == 0 else os._exit(0)')
        start = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            run_bounded([sys.executable, '-c', script], timeout=.25)
        self.assertLess(time.monotonic() - start, 2)

    def test_classifier_rejects_real_overflow(self):
        for descriptor in (1, 2):
            with self.subTest(descriptor=descriptor), tempfile.TemporaryDirectory() as directory:
                binary = self.overflowing_cli(directory, descriptor)
                class Hub:
                    data = Path(directory)
                    def isolation_flags(self, engine, binary): return ['--safe-mode']
                self.assertIsNone(cli_choice({'classifier_engine': 'claude', 'claude_bin': binary},
                                              ['a', 'b'], 'choose', hub=Hub()))

    def test_cli_probes_reject_real_overflow(self):
        from hub import Hub as Application
        for descriptor in (1, 2):
            with self.subTest(descriptor=descriptor), tempfile.TemporaryDirectory() as directory:
                binary = self.overflowing_cli(directory, descriptor)
                class Hub(IsolationMixin):
                    lock = threading.RLock()
                    config = {'detect_engines': True, 'claude_bin': binary, 'codex_bin': binary}
                    def engine_catalog(self): return self.engine_auth
                hub = Hub()
                self.assertEqual(hub.claude_stream_flags(binary), [])
                with self.assertRaisesRegex(RuntimeError, 'cannot isolate rules'):
                    hub.isolation_flags('claude', binary)
                self.assertEqual(Application.probe_engines(hub), {'claude': 'unknown', 'codex': 'unknown'})

    def test_tailscale_status_caps_both_pipes(self):
        from unittest.mock import patch
        from hub_security import local_tailscale_status
        for descriptor in (1, 2):
            with tempfile.TemporaryDirectory() as directory:
                binary = Path(self.overflowing_cli(directory, descriptor))
                binary.rename(binary.with_name('tailscale'))
                with patch.dict(os.environ, {'PATH': directory}), self.assertRaises(OutputLimitExceeded):
                    local_tailscale_status()


if __name__ == '__main__':
    unittest.main()
