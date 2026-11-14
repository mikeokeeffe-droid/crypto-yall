"""Offline unit tests for the narrow no-connect socket-denial probe."""
import errno
import socket
import unittest

from collector_review.ip_socket_denial_probe import check_ip_socket_creation_denied


class SocketDenialProbeTests(unittest.TestCase):
    def test_ipv4_ipv6_denied_is_pass(self):
        calls = []

        def denied(family, kind):
            calls.append((family, kind))
            raise OSError(errno.EAFNOSUPPORT, "denied")

        success, labels = check_ip_socket_creation_denied(denied)
        self.assertTrue(success)
        self.assertEqual(labels, ("ipv4", "ipv6"))
        self.assertEqual(calls, [
            (socket.AF_INET, socket.SOCK_STREAM),
            (socket.AF_INET6, socket.SOCK_STREAM),
        ])

    def test_unexpected_success_closes_without_connecting(self):
        class NoNetworkSocket:
            closed = False

            def close(self):
                self.closed = True

            def connect(self, *_):
                raise AssertionError("connect must never be called")

        obj = NoNetworkSocket()
        success, labels = check_ip_socket_creation_denied(
            lambda family, kind: obj)
        self.assertFalse(success)
        self.assertEqual(labels, ())
        self.assertTrue(obj.closed)

    def test_unexpected_error_fails_closed(self):
        def unexpected(family, kind):
            raise OSError(errno.EINVAL, "unexpected")

        success, labels = check_ip_socket_creation_denied(unexpected)
        self.assertFalse(success)
        self.assertEqual(labels, ())

    def test_permission_denied_is_accepted(self):
        success, labels = check_ip_socket_creation_denied(
            lambda family, kind: (_ for _ in ()).throw(
                OSError(errno.EPERM, "denied")))
        self.assertTrue(success)
        self.assertEqual(labels, ("ipv4", "ipv6"))


if __name__ == "__main__":
    unittest.main()
