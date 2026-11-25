"""Local AF_UNIX mock-only protocol integration; never accesses an exchange."""
import json
import os
import socket
import threading
import unittest

from readonly_connection_review.linux_process_provenance_review_offline import read_linux_process_provenance
from readonly_connection_review.testnet_egress_policy_review_offline import load_review_contract, PolicyHold
from readonly_connection_review.unix_gateway_protocol_review_offline import (
    REQUEST, handle_connected_review_socket,
)

NONCE = "0123456789abcdef0123456789abcdef"


@unittest.skipUnless(
    os.name == "posix" and hasattr(socket, "SO_PEERCRED")
    and os.path.exists("/proc/self/stat"),
    "Linux SO_PEERCRED /proc required",
)
class UnixGatewayProtocolOfflineTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.a.settimeout(2)
        self.b.settimeout(2)
        self.args = dict(
            expected_uid=os.getuid(), expected_gid=os.getgid(),
            expected_provenance=read_linux_process_provenance(os.getpid()),
            approved_review_lease=True, test_nonce=NONCE,
            policy=load_review_contract(), clock=lambda: 100.0,
        )

    def tearDown(self):
        self.a.close()
        self.b.close()

    def test_fixed_command_returns_only_mock_counts_over_local_socket(self):
        if os.getuid() == 0 or os.getgid() == 0:
            self.skipTest("unprivileged identity required")
        self.b.sendall(REQUEST)
        self.assertEqual(handle_connected_review_socket(self.a, **self.args), 2)
        payload = json.loads(self.b.recv(256).decode("ascii"))
        self.assertEqual(payload["status"], "MOCK_OFFLINE_REVIEW_ONLY")
        self.assertEqual(payload["positions"], 0)
        self.assertEqual(payload["open_orders"], 0)
        self.assertIs(payload["api_connected"], False)
        self.assertIs(payload["trading_enabled"], False)

    def test_rejects_exchange_or_arbitrary_commands(self):
        for command in (
            b"POST /exchange\n", b"GET /info\n",
            b"READ_TESTNET_ACCOUNT_COUNTS_OFFLINE_V1\nEXTRA",
            b"READ_TESTNET_ACCOUNT_COUNTS_OFFLINE_V1",
            b'{"type":"order"}\n',
        ):
            a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                b.sendall(command)
                with self.subTest(command=command), self.assertRaises(PolicyHold):
                    handle_connected_review_socket(a, **self.args)
            finally:
                a.close()
                b.close()

    def test_denies_missing_review_authorization(self):
        self.b.sendall(REQUEST)
        with self.assertRaises(PolicyHold):
            handle_connected_review_socket(
                self.a, **dict(self.args, approved_review_lease=False)
            )

    def test_denies_incorrect_process_identity(self):
        self.b.sendall(REQUEST)
        with self.assertRaises(PolicyHold):
            handle_connected_review_socket(
                self.a, **dict(self.args, expected_uid=os.getuid() + 1)
            )

    def test_denies_network_authority_in_review_policy(self):
        self.b.sendall(REQUEST)
        modified_policy = dict(self.args["policy"], network_authorized=True)
        with self.assertRaises(PolicyHold):
            handle_connected_review_socket(
                self.a, **dict(self.args, policy=modified_policy)
            )


if __name__ == "__main__":
    unittest.main()
