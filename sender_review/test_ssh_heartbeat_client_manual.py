"""Offline tests for manual-only SSH heartbeat client; no SSH/network actions."""
import base64
import json
import os
from unittest import TestCase
from unittest.mock import patch
from sender_review import ssh_heartbeat_client_manual as client


def valid_host_key():
    blob = (len(b"ssh-ed25519").to_bytes(4, "big") + b"ssh-ed25519"
            + (32).to_bytes(4, "big") + bytes(range(32)))
    return "ssh-ed25519 " + base64.b64encode(blob).decode("ascii")


class ManualHeartbeatClientTests(TestCase):
    def test_pins_only_fixed_ed25519_host(self):
        key = valid_host_key()
        expected = "2.29.170.69 " + key + "\n"
        self.assertEqual(client.pinned_known_hosts_line(key), expected)
        self.assertEqual(client.pinned_known_hosts_line("2.29.170.69 " + key), expected)
        for bad in ("", "ssh-rsa AAAA", "2.29.170.70 " + key,
                    "example.org " + key, key + "\n"+key,
                    key.replace("ssh-ed25519", "ssh-rsa"),
                    "ssh-ed25519 AAAA", "ssh-ed25519 !!!!!"):
            with self.subTest(bad=bad[:50]):
                with self.assertRaises(client.HeartbeatHold):
                    client.pinned_known_hosts_line(bad)

    def test_liveness_ack_never_approves_trading(self):
        nonce = "a" * 32
        request = client.challenge(1771880000, nonce)
        self.assertEqual(json.loads(request)["kind"], "heartbeat")
        ack = {"v": 1, "kind": "heartbeat_ack", "nonce": nonce,
               "server_nonce": "b" * 32, "received": 1771880000,
               "authority": "none"}
        payload = (json.dumps(ack, separators=(",", ":")) + "\n").encode()
        self.assertTrue(client.check_ack(payload, nonce=nonce, now=1771880000))
        for field, value in (("nonce", "c" * 32), ("authority", "trade"),
                             ("received", 1771880050), ("kind", "order_ack")):
            bad = dict(ack, **{field: value})
            with self.subTest(field=field):
                with self.assertRaises(client.HeartbeatHold):
                    client.check_ack((json.dumps(bad) + "\n").encode(),
                                     nonce=nonce, now=1771880000)
        with self.assertRaises(client.HeartbeatHold):
            client.check_ack(payload + payload, nonce=nonce, now=1771880000)

    def test_main_not_called_without_manual_approval(self):
        for changed in ({}, {"GITHUB_ACTIONS": "true"},
                        {"GITHUB_ACTIONS": "true",
                         "GITHUB_REF": "refs/heads/main"},
                        {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/anything",
                         "HEARTBEAT_MANUAL_CONFIRM": "yes"}):
            with patch.dict(os.environ, changed, clear=True):
                with self.assertRaises(client.HeartbeatHold):
                    client.main()

    def test_rejects_unusable_private_key_without_creating_file(self):
        with self.assertRaises(client.HeartbeatHold):
            client._write_private_key(None, "not a key")


if __name__ == "__main__":
    import unittest
    unittest.main()
