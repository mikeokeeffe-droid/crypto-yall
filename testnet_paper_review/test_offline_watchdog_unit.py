"""Static offline review of the network-disabled systemd rehearsal unit."""
import configparser
from pathlib import Path
import unittest

UNIT = Path(__file__).parent / "deployment/testnet-watchdog-offline-rehearsal.service"
ROOT = "/opt/crypto-yall/watchdog_review"
COMMAND = (
    "/usr/bin/python3 -E -s -B -m unittest "
    "testnet_paper_review.test_offline_watchdog_policy "
    "testnet_paper_review.test_offline_watchdog_receipt_bridge "
    "testnet_paper_review.test_offline_watchdog_alert_rehearsal -v"
)

class WatchdogUnitTests(unittest.TestCase):
    def setUp(self):
        self.unit = configparser.ConfigParser(interpolation=None, strict=True)
        self.unit.optionxform = str
        self.unit.read_string(UNIT.read_text(encoding="utf-8"))

    def test_exact_unit_and_no_install_or_timer(self):
        self.assertEqual(self.unit.sections(), ["Unit", "Service"])
        self.assertFalse(self.unit.defaults())
        self.assertEqual(dict(self.unit["Unit"]), {
            "Description": "Crypto Yall Testnet watchdog offline service rehearsal",
            "ConditionPathIsDirectory": ROOT,
        })

    def test_exact_service_allowlist(self):
        self.assertEqual(dict(self.unit["Service"]), {
            "Type": "oneshot",
            "WorkingDirectory": ROOT,
            "ExecStart": COMMAND,
            "DynamicUser": "yes",
            "NoNewPrivileges": "yes",
            "ProtectSystem": "strict",
            "ProtectHome": "yes",
            "PrivateDevices": "yes",
            "PrivateTmp": "yes",
            "PrivateNetwork": "yes",
            "RestrictAddressFamilies": "AF_UNIX",
            "IPAddressDeny": "any",
            "CapabilityBoundingSet": "",
            "AmbientCapabilities": "",
            "ProtectKernelTunables": "yes",
            "ProtectKernelModules": "yes",
            "ProtectControlGroups": "yes",
            "RestrictSUIDSGID": "yes",
            "LockPersonality": "yes",
            "SystemCallArchitectures": "native",
            "UMask": "0077",
            "TimeoutStartSec": "60",
            "Restart": "no",
            "StandardOutput": "journal",
            "StandardError": "journal",
        })

if __name__ == "__main__":
    unittest.main()
