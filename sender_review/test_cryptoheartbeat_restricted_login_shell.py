"""Offline regression tests of the *uninstalled* restricted SSH login shell."""
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent / "deployment"
SHELL = HERE / "cryptoheartbeat-login-shell.sh.example"


class CryptoheartbeatRestrictedLoginShellTests(unittest.TestCase):
    def test_only_one_fixed_exec_and_no_shell_delegation(self):
        src = SHELL.read_text(encoding="utf-8")
        live = [line.strip() for line in src.splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
        self.assertEqual(live, [
            "exec /usr/bin/env -i PATH=/usr/bin:/bin LANG=C "
            "/usr/bin/python3 -I "
            "/usr/local/libexec/crypto-yall/ssh_heartbeat_stdio_review_only.py",
        ])
        self.assertTrue(SHELL.name.endswith(".example"))

    def test_fixed_root_owned_path_and_no_live_code_references(self):
        src = SHELL.read_text(encoding="utf-8")
        self.assertNotIn("HL_PRIVATE_KEY", src)
        self.assertNotIn("hyperliquid_executor", src)
        self.assertNotIn("testadmin/crypto-yall-monitor/repo/", src)


if __name__ == "__main__":
    unittest.main()
