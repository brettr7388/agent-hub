"""Child shutdown keeps its guarantees when process-group signaling is restricted."""
import signal
import unittest
from unittest import mock
import hub


class ChildSignals(unittest.TestCase):
    def test_exited_child_and_exit_during_group_signal(self):
        child = mock.Mock(pid=12345)
        child.poll.return_value = 0
        with mock.patch.object(hub.os, 'killpg') as group:
            hub.signal_child(child, signal.SIGTERM)
            group.assert_not_called()
        child.poll.side_effect = [None, 0]
        with mock.patch.object(hub.os, 'killpg', side_effect=PermissionError):
            hub.signal_child(child, signal.SIGTERM)
        child.send_signal.assert_not_called()

    def test_live_group_denial_uses_only_the_tracked_child(self):
        child = mock.Mock(pid=12345)
        child.poll.return_value = None
        with mock.patch.object(hub.os, 'killpg', side_effect=PermissionError) as group:
            hub.signal_child(child, signal.SIGTERM)
        group.assert_called_once_with(child.pid, signal.SIGTERM)
        child.send_signal.assert_called_once_with(signal.SIGTERM)

    def test_genuine_denial_is_not_hidden(self):
        child = mock.Mock(pid=12345)
        child.poll.return_value = None
        child.send_signal.side_effect = PermissionError('direct signal denied')
        with mock.patch.object(hub.os, 'killpg', side_effect=PermissionError):
            with self.assertRaisesRegex(PermissionError, 'direct signal denied'):
                hub.signal_child(child, signal.SIGKILL)

    def test_normal_group_and_missing_group(self):
        child = mock.Mock(pid=12345)
        child.poll.return_value = None
        with mock.patch.object(hub.os, 'killpg') as group:
            hub.signal_child(child, signal.SIGKILL)
            group.assert_called_once_with(child.pid, signal.SIGKILL)
        with mock.patch.object(hub.os, 'killpg', side_effect=ProcessLookupError):
            hub.signal_child(child, signal.SIGTERM)
        child.send_signal.assert_not_called()
