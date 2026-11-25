"""Offline integration tests. No network, service, SSH, or trading calls."""
import os
import socket
import unittest

from readonly_connection_review.offline_gateway_integration_review import (
    review_offline_identity_to_frames,
)
from readonly_connection_review.linux_process_provenance_review_offline import (
    read_linux_process_provenance,
)
from readonly_connection_review.testnet_egress_policy_review_offline import (
    PolicyHold, inspect_synthetic_requests, load_review_contract,
)

NONCE = "0123456789abcdef0123456789abcdef"


@unittest.skipUnless(
    os.name == "posix" and hasattr(socket, "SO_PEERCRED")
    and os.path.exists("/proc/self/stat"),
    "Linux /proc and AF_UNIX SO_PEERCRED required",
)
class OfflineGatewayIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.provenance = read_linux_process_provenance(os.getpid())
        self.policy = load_review_contract()
        self.args = dict(
            expected_uid=os.getuid(), expected_gid=os.getgid(),
            expected_provenance=self.provenance,
            approved_review_lease=True, test_nonce=NONCE,
            policy=self.policy, clock=lambda: 100.0,
        )

    def tearDown(self):
        self.a.close()
        self.b.close()

    def test_exact_two_safe_frames_on_local_verified_peer(self):
        if os.getuid() == 0 or os.getgid() == 0:
            self.skipTest("unprivileged test identity required")
        frames = review_offline_identity_to_frames(self.a, **self.args)
        self.assertEqual(len(frames), 2)
        self.assertTrue(inspect_synthetic_requests(self.policy, frames))
        self.assertIs(self.policy["network_authorized"], False)

    def test_wrong_uid_is_denied(self):
        with self.assertRaises(PolicyHold):
            review_offline_identity_to_frames(
                self.a, **dict(self.args, expected_uid=os.getuid() + 1)
            )

    def test_different_process_provenance_is_denied(self):
        wrong = self.provenance._replace(start_ticks=self.provenance.start_ticks + 1)
        with self.assertRaises(PolicyHold):
            review_offline_identity_to_frames(
                self.a, **dict(self.args, expected_provenance=wrong)
            )

    def test_wrong_executable_and_cgroup_are_denied(self):
        for wrong in (
            self.provenance._replace(executable="/tmp/unapproved"),
            self.provenance._replace(cgroup_v2="/unapproved.slice"),
        ):
            with self.subTest(wrong=wrong), self.assertRaises(PolicyHold):
                review_offline_identity_to_frames(
                    self.a, **dict(self.args, expected_provenance=wrong)
                )

    def test_no_approval_is_denied(self):
        with self.assertRaises(PolicyHold):
            review_offline_identity_to_frames(
                self.a, **dict(self.args, approved_review_lease=False)
            )

    def test_no_network_authority_even_in_review_contract(self):
        policy = dict(self.policy, network_authorized=True)
        with self.assertRaises(PolicyHold):
            review_offline_identity_to_frames(
                self.a, **dict(self.args, policy=policy)
            )


if __name__ == "__main__":
    unittest.main()
