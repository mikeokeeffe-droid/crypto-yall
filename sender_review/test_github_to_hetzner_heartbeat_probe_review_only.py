"""Offline tests for GitHub → Hetzner SSH probe; no network or secrets."""
import base64
import json
import re
import os
import stat
import sys
from pathlib import Path
import struct
import subprocess
import unittest
from unittest.mock import patch

from sender_review.github_to_hetzner_heartbeat_probe_review_only import (
    HOST, HeartbeatProbeError, _run_ssh_bounded, challenge, pinned_host_key_line, probe, verify_ack,
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
            self.assertEqual(set(kwargs['env']), {'PATH', 'LANG', 'HOME'})
            self.assertNotIn('HETZNER_HEARTBEAT_SSH_KEY', kwargs['env'])
            self.assertNotIn('HETZNER_HEARTBEAT_HOST_KEY_ED25519', kwargs['env'])
            self.assertIn("StrictHostKeyChecking=yes", args)
            self.assertIn("ClearAllForwardings=yes", args)
            self.assertIn("BatchMode=yes", args)
            self.assertIn("-T", args)
            self.assertNotIn("StrictHostKeyChecking=no", args)
            self.assertIn("ProxyCommand=none", args)
            self.assertIn("ProxyJump=none", args)
            self.assertIn("RequestTTY=no", args)
            self.assertIn('HostKeyAlgorithms=ssh-ed25519', args)
            self.assertIn('IdentityAgent=none', args)
            self.assertIn('UpdateHostKeys=no', args)
            self.assertIn('-F', args)
            self.assertEqual(args[args.index('-F')+1], '/dev/null')
            key_path = Path(args[args.index("-i") + 1])
            self.assertEqual(stat.S_IMODE(key_path.stat().st_mode), 0o600)
            host_opt = next(x for x in args if x.startswith("UserKnownHostsFile="))
            host_path = Path(host_opt.partition("=")[2])
            self.assertEqual(stat.S_IMODE(host_path.stat().st_mode), 0o600)
            self.assertEqual(host_path.read_text(), HOST + ' ssh-ed25519 ' + ssh_blob() + '\n')
            reply = json.dumps({"v": 1, "kind": "heartbeat_ack",
                                "nonce": NONCE, "server_nonce": "b"*32,
                                "received": NOW, "authority": "none"}).encode("ascii")
            return subprocess.CompletedProcess(args, 0, stdout=reply, stderr=b"")
        self.assertTrue(probe(private_key=DUMMY_PRIVATE_KEY,
                              host_public_key=HOSTKEY, ssh_run=fake_run,
                              now=NOW, nonce=NONCE))
        self.assertEqual(len(inspected), 1)

    def test_review_workflow_requires_separate_environment_secrets(self):
        """No original repo-secret names and no unprotected heartbeat job."""
        wf = Path('.github/workflows/manual-hetzner-ssh-heartbeat-review.yml').read_text()
        self.assertRegex(wf, r'(?m)^    environment: hetzner-heartbeat-review\s*
        self.assertIn("github.ref == 'refs/heads/main'", wf)
        self.assertIn("inputs.confirm == 'RUN_READONLY_HEARTBEAT'", wf)
        self.assertIn('secrets.HETZNER_HEARTBEAT_REVIEW_ENV_PRIVATE_KEY', wf)
        self.assertIn('secrets.HETZNER_HEARTBEAT_REVIEW_ENV_HOST_KEY_ED25519', wf)
        self.assertNotIn('secrets.HETZNER_HEARTBEAT_SSH_KEY', wf)
        self.assertNotIn('secrets.HETZNER_HEARTBEAT_HOST_KEY_ED25519', wf)
        self.assertNotIn('on: push', wf)
        self.assertNotIn('on: schedule', wf)

    def test_bounded_local_process_captures_small_ack(self):
        # Local python process only, never an SSH/network connection.
        p = [sys.executable, '-c',
             'import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b"OK")']
        r = _run_ssh_bounded(p, input=b"hello", capture_output=True, timeout=3,
                             check=False)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, b"OK")

    def test_bounded_local_process_rejects_overflow(self):
        p = [sys.executable, '-c',
             'import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b"x"*501); sys.stdout.flush()']
        with self.assertRaisesRegex(HeartbeatProbeError, "maximum length"):
            _run_ssh_bounded(p, input=b"hello", capture_output=True, timeout=3,
                             check=False)

    def test_bounded_local_process_times_out(self):
        p = [sys.executable, '-c',
             'import time,sys; sys.stdin.buffer.read(); time.sleep(3)']
        with self.assertRaises(subprocess.TimeoutExpired):
            _run_ssh_bounded(p, input=b"hello", capture_output=True, timeout=0.3,
                             check=False)

    def test_nonzero_exit_never_echoes_stderr(self):
        def failed_run(args, **kw):
            return subprocess.CompletedProcess(args, 255, stdout=b"",
                                               stderr=b"DO_NOT_LOG_SECRET")
        with self.assertRaisesRegex(HeartbeatProbeError,
                                    "SSH probe failed"):
            probe(private_key=DUMMY_PRIVATE_KEY, host_public_key=HOSTKEY,
                  ssh_run=failed_run, now=NOW, nonce=NONCE)

    def test_no_network_when_input_missing(self):
        with patch("sender_review.github_to_hetzner_heartbeat_probe_review_only.subprocess.Popen",
                   side_effect=AssertionError("network not allowed")):
            with self.assertRaises(HeartbeatProbeError):
                probe(private_key="", host_public_key=HOSTKEY)


if __name__ == "__main__":
    unittest.main()
)
        self.assertIn("github.ref == 'refs/heads/main'", wf)
        self.assertIn("inputs.confirm == 'RUN_READONLY_HEARTBEAT'", wf)
        self.assertIn('secrets.HETZNER_HEARTBEAT_REVIEW_ENV_PRIVATE_KEY', wf)
        self.assertIn('secrets.HETZNER_HEARTBEAT_REVIEW_ENV_HOST_KEY_ED25519', wf)
        self.assertNotIn('secrets.HETZNER_HEARTBEAT_SSH_KEY', wf)
        self.assertNotIn('secrets.HETZNER_HEARTBEAT_HOST_KEY_ED25519', wf)
        self.assertNotIn('on: push', wf)
        self.assertNotIn('on: schedule', wf)

    def test_bounded_local_process_captures_small_ack(self):
        # Local python process only, never an SSH/network connection.
        p = [sys.executable, '-c',
             'import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b"OK")']
        r = _run_ssh_bounded(p, input=b"hello", capture_output=True, timeout=3,
                             check=False)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, b"OK")

    def test_bounded_local_process_rejects_overflow(self):
        p = [sys.executable, '-c',
             'import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b"x"*501); sys.stdout.flush()']
        with self.assertRaisesRegex(HeartbeatProbeError, "maximum length"):
            _run_ssh_bounded(p, input=b"hello", capture_output=True, timeout=3,
                             check=False)

    def test_bounded_local_process_times_out(self):
        p = [sys.executable, '-c',
             'import time,sys; sys.stdin.buffer.read(); time.sleep(3)']
        with self.assertRaises(subprocess.TimeoutExpired):
            _run_ssh_bounded(p, input=b"hello", capture_output=True, timeout=0.3,
                             check=False)

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
