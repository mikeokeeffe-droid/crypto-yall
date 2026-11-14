"""Static review of an inert, network-denied example systemd unit.

Parsing a unit file does NOT prove that systemd supports or enforces these
settings on a target host. No unit is installed or started here.
"""
from pathlib import Path
import unittest

UNIT = Path(__file__).parent / "deployment/testnet-collector-offline-review.service.example"


def directives(text):
    section = None
    service = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if "=" not in line:
            raise ValueError("unexpected unit line")
        name, value = line.split("=", 1)
        if section == "Service":
            service.setdefault(name, []).append(value)
        elif section == "Install":
            raise ValueError("unit must not have Install section")
    return service


class OfflineSystemdUnitReview(unittest.TestCase):
    def test_review_unit_is_noninstallable_and_network_disabled(self):
        text = UNIT.read_text(encoding="utf-8")
        s = directives(text)
        required = {
            "Type": "oneshot",
            "DynamicUser": "yes",
            "NoNewPrivileges": "yes",
            "CapabilityBoundingSet": "",
            "AmbientCapabilities": "",
            "PrivateNetwork": "yes",
            "RestrictAddressFamilies": "AF_UNIX",
            "IPAddressDeny": "any",
            "ProtectSystem": "strict",
            "ProtectHome": "yes",
            "PrivateTmp": "yes",
            "PrivateDevices": "yes",
            "RestrictSUIDSGID": "yes",
            "UMask": "0077",
        }
        for key, value in required.items():
            with self.subTest(key=key):
                self.assertEqual(s.get(key), [value])
        self.assertEqual(s.get("SystemCallFilter"), ["@system-service"])
        self.assertEqual(len(s["ExecStart"]), 3)
        self.assertIn("-m collector_review.host_isolation_probe",
                      s["ExecStart"][0])
        self.assertIn("-m collector_review.ip_socket_denial_probe",
                      s["ExecStart"][1])
        self.assertIn("-m unittest", s["ExecStart"][2])
        self.assertTrue(all("market_open" not in step
                            for step in s["ExecStart"]))
        for forbidden in ("EnvironmentFile", "LoadCredential",
                          "LoadCredentialEncrypted", "ExecStartPre",
                          "ExecStartPost", "RootDirectory",
                          "ReadWritePaths", "BindPaths"):
            self.assertNotIn(forbidden, s)
        # Strip comments before checking for the actual INI section header.
        actual_lines = [line.strip() for line in text.splitlines()
                        if not line.lstrip().startswith(("#", ";"))]
        self.assertNotIn("[Install]", actual_lines)

    def test_static_guard_detects_removed_isolation(self):
        text=UNIT.read_text(encoding="utf-8")
        for original, replacement in (
            ("PrivateNetwork=yes", "PrivateNetwork=no"),
            ("RestrictAddressFamilies=AF_UNIX",
             "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6"),
            ("DynamicUser=yes", "DynamicUser=no"),
            ("IPAddressDeny=any", "IPAddressAllow=any"),
        ):
            with self.subTest(original=original):
                edited=directives(text.replace(original,replacement))
                self.assertNotEqual(edited, directives(text))
        with self.assertRaises(ValueError):
            directives(text + "\n[Install]\nWantedBy=multi-user.target\n")


if __name__ == "__main__":
    unittest.main()
