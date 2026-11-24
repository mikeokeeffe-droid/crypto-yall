"""Offline Linux AF_UNIX SO_PEERCRED tests; no network or production gateway."""
import os
import socket
import unittest

from readonly_connection_review.kernel_unix_peer_review_offline import (
    kernel_unix_peer_credentials, review_kernel_peer_offline
)
from readonly_connection_review.offline_gateway_peer_admission import OfflinePeerAdmission
from readonly_connection_review.testnet_egress_policy_review_offline import PolicyHold

NONCE = "0123456789abcdef0123456789abcdef"


@unittest.skipUnless(
    os.name == "posix" and hasattr(socket, "SO_PEERCRED"),
    "Linux SO_PEERCRED required",
)
class KernelUnixPeerOfflineTests(unittest.TestCase):
    def test_kernel_credentials_on_unnamed_local_socket_pair(self):
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            creds = kernel_unix_peer_credentials(a)
            self.assertEqual(creds.pid, os.getpid())
            self.assertEqual(creds.uid, os.getuid())
            self.assertEqual(creds.gid, os.getgid())
            self.assertEqual(kernel_unix_peer_credentials(b), creds)
        finally:
            a.close()
            b.close()

    def test_kernel_identity_passes_synthetic_admission_once(self):
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            fixture = OfflinePeerAdmission(
                expected_uid=os.getuid(),
                expected_gid=os.getgid(),
                expected_nonce=NONCE,
            ) if os.getuid() > 0 and os.getgid() > 0 else None
            if fixture is None:
                self.skipTest("unprivileged Linux test identity required")
            self.assertTrue(review_kernel_peer_offline(
                a, fixture, approved_review_lease=True, nonce=NONCE
            ))
            with self.assertRaises(PolicyHold):
                review_kernel_peer_offline(
                    a, fixture, approved_review_lease=True, nonce=NONCE
                )
        finally:
            a.close()
            b.close()

    def test_wrong_expected_peer_denied(self):
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            fixture = OfflinePeerAdmission(
                expected_uid=os.getuid() + 1,
                expected_gid=max(os.getgid(), 1),
                expected_nonce=NONCE,
            )
            with self.assertRaises(PolicyHold):
                review_kernel_peer_offline(
                    a, fixture, approved_review_lease=True, nonce=NONCE
                )
        finally:
            a.close()
            b.close()

    def test_inet_socket_and_arbitrary_object_rejected(self):
        inet = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with self.assertRaises(PolicyHold):
                kernel_unix_peer_credentials(inet)
            with self.assertRaises(PolicyHold):
                kernel_unix_peer_credentials({"uid": os.getuid()})
        finally:
            inet.close()

    def test_datagram_socket_rejected(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            with self.assertRaises(PolicyHold):
                kernel_unix_peer_credentials(sock)
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
