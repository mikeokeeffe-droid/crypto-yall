"""Static regression tests: SSH heartbeat restrictions remain REVIEW ONLY."""
from pathlib import Path
import unittest

TEMPLATE = (Path(__file__).resolve().parent / "deployment"
            / "99-cryptoheartbeat-sshd.conf.example")


class CryptoheartbeatSshTemplateTests(unittest.TestCase):
    def test_restrictions_present_and_nontrading(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        required = (
            "Match User cryptoheartbeat",
            "AuthenticationMethods publickey",
            "PasswordAuthentication no",
            "KbdInteractiveAuthentication no",
            "ForceCommand /usr/bin/python3 -I /usr/local/libexec/crypto-yall/ssh_heartbeat_stdio_review_only.py",
            "DisableForwarding yes",
            "AllowTcpForwarding no",
            "AllowStreamLocalForwarding no",
            "AllowAgentForwarding no",
            "X11Forwarding no",
            "PermitTTY no",
            "PermitUserRC no",
            "PermitTunnel no",
            "PermitUserEnvironment no",
        )
        for item in required:
            with self.subTest(item=item):
                self.assertIn(item, text)
        self.assertEqual(text.count("Match User cryptoheartbeat"), 1)
        self.assertNotIn("HL_PRIVATE_KEY", text)
        self.assertNotIn("execute-trades", text)
        self.assertNotIn("market_open", text)

    def test_requires_review_and_does_not_weaken_existing_access(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        self.assertTrue(TEMPLATE.name.endswith(".example"))
        self.assertIn("Do NOT just", text)
        self.assertIn("nologin", text)
        self.assertIn("sudo sshd -t", text)
        self.assertIn("HOLD rather than unlock", text)
        self.assertNotIn("Match All", text)
        self.assertNotIn("AllowUsers", text)


if __name__ == "__main__":
    unittest.main()
