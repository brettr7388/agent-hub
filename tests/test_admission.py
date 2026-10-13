"""PASS13 regression for ordinary browser connection bursts; no sockets are opened."""
import threading
import unittest
from unittest.mock import Mock, patch

import hub_security as security


class BrowserBurstAdmission(unittest.TestCase):
    def test_six_parallel_first_load_requests_are_admitted_then_ip_limit_applies(self):
        server = security.BoundedThreadingHTTPServer.__new__(security.BoundedThreadingHTTPServer)
        server._handler_slots = threading.BoundedSemaphore(security.MAX_HANDLERS)
        server._admission_lock = threading.Lock()
        server._admitted = {}
        server._unauth_by_ip = {}
        server._unauth_total = 0
        server._unauth_limit = security.MAX_HANDLERS - security.AUTH_RESERVED_HANDLERS
        server._max_unauth_per_ip = security.MAX_UNAUTH_PER_IP
        server.shutdown_request = Mock()
        first_load = [Mock() for _ in range(6)]
        for request in first_load:
            request.recv.return_value = b''

        with patch.object(security.ThreadingHTTPServer, 'process_request') as spawned:
            for request in first_load:
                server.process_request(request, ('192.0.2.10', 4000))

            self.assertEqual(spawned.call_count, 6)
            self.assertEqual(server._unauth_by_ip['192.0.2.10'], 6)

            extra = [Mock() for _ in range(security.MAX_UNAUTH_PER_IP - 6)]
            for request in extra:
                request.recv.return_value = b''
                server.process_request(request, ('192.0.2.10', 4000))
            self.assertEqual(spawned.call_count, security.MAX_UNAUTH_PER_IP)

            over_limit = Mock()
            over_limit.recv.return_value = b''
            server.process_request(over_limit, ('192.0.2.10', 4000))
            server.shutdown_request.assert_called_once_with(over_limit)
            self.assertEqual(spawned.call_count, security.MAX_UNAUTH_PER_IP)
            self.assertEqual(server._unauth_total, security.MAX_UNAUTH_PER_IP)

        for request in first_load + extra:
            server._release_admission(request)
            server._handler_slots.release()
        self.assertEqual(server._unauth_total, 0)


if __name__ == '__main__':
    unittest.main()
