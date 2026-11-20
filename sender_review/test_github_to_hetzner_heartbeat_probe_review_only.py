"""Offline tests for GitHub → Hetzner SSH probe; no network or secrets."""
import base64
import json
import struct
import subprocess
import unittest
from unittest.mock import patch

from sender_review.github_to_hetzner_heartbeat_probe_review_only import (
    HOST, HeartbeatProbeError, challenge, pinned_host_key_line, probe, verify_ack,
)

NOW = 1800000000
NONCE = "a" * 32
def ssh_blob():
    def field(data):
        return struct.pack(">I", len(data)) + data
    return base64.b64encode(field(b"ssh-ed25519") + field(b"\0"*32)).decode("ascii")
HOSTKEY = "ssh-ed25519 " + ssh_blob() + " test"
DUMMY_PRIVATE_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nDUMMY\n-----END OPENSSH PRIVATE KEY-----"


class GitHubToHetznerProbeReviewTests(unittest.TestCase):
    def test_valid_challenge_and_ack(self):
        frame = json.loads(challenge(NOW, NONCE))
        self.assertEqual(set(frame), {"v", "kind", "nonce", "sent"})
        self.assertEqual(frame["kind"], "heartbeat")
        ack = json.dumps({"v": 1, "kind": "heartbeat_ack", "nonce": NONCE,
                          "server_nonce": "b"*32, "received": NOW,
                          "authority": "none"}).encode("ascii")
        self.assertTrue(verify_ack(ack, nonce=NONCE, now=NOW))

    def test_rejects_wrong_ack_nonce_age_and_authority(self):
        base = {"v": 1, "kind": "heartbeat_ack", "nonce": NONCE,
                "server_nonce": "b"*32, "received": NOW, "authority": "none"}
        for patch_values in (
            {"nonce": "c"*32}, {"received": NOW-16},
            {"received": NOW+16}, {"authority": "trade"},
            {"kind": "trade_ack"}, {"v": True}, {"server_nonce": "invalid"},
            {"action": "buy"}, {"received": 1.0},
        ):
            with self.subTest(case=patch_values), self.assertRaises(HeartbeatProbeError):
                verify_ack(json.dumps({**base, **patch_values}).encode("ascii"),
                           nonce=NONCE, now=NOW)
        with self.assertRaises(HeartbeatProbeError):
            verify_ack(b'{"v":1,"v":1}', nonce=NONCE, now=NOW)

    def test_known_hosts_must_be_fixed_ed25519_key(self):
        self.assertEqual(pinned_host_key_line(HOSTKEY),
                         HOST + " ssh-ed25519 " + ssh_blob() + "\n")
        for invalid in ("", "ssh-rsa " + ssh_blob(),
                        "2.29.170.69 " + HOSTKEY, "ssh-ed25519 garbage", "localhost"):
            with self.subTest(value=invalid), self.assertRaises(HeartbeatProbeError):
                pinned_host_key_line(invalid)

    def test_probe_uses_pinned_host_and_no_tty_or_forwarding(self):
        inspected = []
        def fake_run(args, **kwargs):
            inspected.append((args, kwargs))
            outgoing = json.loads(kwargs["input"])
            self.assertEqual(outgoing["nonce"], NONCE)
            self.assertIn("StrictHostKeyChecking=yes", args)
            self.assertIn("ClearAllForwardings=yes", args)
            self.assertIn("BatchMode=yes", args)
            self.assertIn("-T", args)
            self.assertNotIn("StrictHostKeyChecking=no", args)
            reply = json.dumps({"v": 1, "kind": "heartbeat_ack",
                                "nonce": NONCE, "server_nonce": "b"*32,
                                "received": NOW, "authority": "none"}).encode("ascii")
            return subprocess.CompletedProcess(args, 0, stdout=reply, stderr=b"")
        self.assertTrue(probe(private_key=DUMMY_PRIVATE_KEY,
                              host_public_key=HOSTKEY, ssh_run=fake_run,
                              now=NOW, nonce=NONCE))
        self.assertEqual(len(inspected), 1)

    def test_nonzero_exit_never_echoes_stderr(self):
        def failed_run(args, **kw):
            return subprocess.CompletedProcess(args, 255, stdout=b"",
                                               stderr=b"DO_NOT_LOG_SECRET")
        with self.assertRaisesRegex(HeartbeatProbeError,
                                    "SSH probe failed"):
            probe(private_key=DUMMY_PRIVATE_KEY, host_public_key=HOSTKEY,
                  ssh_run=failed_run, now=NOW, nonce=NONCE)

    def test_no_network_when_input_missing(self):
        with patch("sender_review.github_to_hetzner_heartbeat_probe_review_only.subprocess.run",
                   side_effect=AssertionError("network not allowed")):
            with self.assertRaises(HeartbeatProbeError):
                probe(private_key="", host_public_key=HOSTKEY)


if __name__ == "__main__":
    unittest.main()
