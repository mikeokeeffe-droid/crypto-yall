"""Static verification of intentionally inert systemd isolation fixture.

No systemctl, systemd-analyze, services, processes or network are executed.
A passing result is NOT proof of host isolation or permission to deploy.
"""
from configparser import ConfigParser
from pathlib import Path
import unittest


UNIT = Path(__file__).with_name("ci_only_readonly_collector_review.service")
EXPECTED_SERVICE = {
    "Type": "oneshot",
    "ExecStart": "/usr/bin/false",
    "DynamicUser": "yes",
    "NoNewPrivileges": "yes",
    "PrivateNetwork": "yes",
    "IPAddressDeny": "any",
    "RestrictAddressFamilies": "AF_UNIX",
    "ProtectSystem": "strict",
    "ProtectHome": "yes",
    "PrivateDevices": "yes",
    "PrivateTmp": "yes",
    "PrivateUsers": "yes",
    "ProtectProc": "invisible",
    "ProcSubset": "pid",
    "ProtectKernelTunables": "yes",
    "ProtectKernelModules": "yes",
    "ProtectControlGroups": "yes",
    "ProtectKernelLogs": "yes",
    "ProtectClock": "yes",
    "RestrictNamespaces": "yes",
    "RestrictRealtime": "yes",
    "RestrictSUIDSGID": "yes",
    "LockPersonality": "yes",
    "MemoryDenyWriteExecute": "yes",
    "SystemCallArchitectures": "native",
    "CapabilityBoundingSet": "",
    "AmbientCapabilities": "",
    "UMask": "0077",
    "RemoveIPC": "yes",
}
EXPECTED_UNIT = {
    "ConditionPathExists": "/run/crypto-yall-readonly-review-never-create",
    "RefuseManualStart": "yes",
}
# Any extra stanza/directive needs explicit review, not silent acceptance.
DISALLOWED = (
    "Environment", "EnvironmentFile", "LoadCredential", "SetCredential",
    "BindPaths", "BindReadOnlyPaths", "ReadWritePaths", "WorkingDirectory",
    "User", "Group", "SupplementaryGroups", "ExecStartPre", "ExecStartPost",
    "ExecStop", "ExecReload", "ExecCondition", "RootDirectory",
    "RootImage", "NetworkNamespacePath", "SocketBindAllow",
    "JoinsNamespaceOf", "PassEnvironment", "UnsetEnvironment",
)


def inspect_unit(source):
    cfg = ConfigParser(interpolation=None, strict=True, delimiters=("=",))
    cfg.optionxform = str
    cfg.read_string(source)
    if set(cfg.sections()) != {"Unit", "Service"}:
        raise ValueError("unexpected unit section; no enable/install/sockets")
    for name, expected in (("Unit", EXPECTED_UNIT),
                           ("Service", EXPECTED_SERVICE)):
        section = cfg[name]
        for key, value in expected.items():
            if section.get(key) != value:
                raise ValueError(f"unsafe or missing {name}.{key}")
    if set(cfg["Service"]) != set(EXPECTED_SERVICE):
        raise ValueError("unexpected service settings need independent review")
    if set(cfg["Unit"]) != set(EXPECTED_UNIT) | {"Description"}:
        raise ValueError("unexpected unit settings need independent review")
    if any(name in cfg["Service"] for name in DISALLOWED):
        raise ValueError("credential/mount/network override forbidden")
    return True


class InertSystemdUnitTests(unittest.TestCase):
    def test_review_unit_contains_only_inert_restrictions(self):
        source = UNIT.read_text("utf-8")
        self.assertIn("DO NOT INSTALL, ENABLE, LINK OR DEPLOY", source)
        self.assertTrue(inspect_unit(source))

    def test_privilege_network_and_secret_exceptions_fail_closed(self):
        source = UNIT.read_text("utf-8")
        mutations = (
            ("PrivateNetwork=yes", "PrivateNetwork=no"),
            ("IPAddressDeny=any", "IPAddressDeny=none"),
            ("ProtectSystem=strict", "ProtectSystem=full"),
            ("ProtectHome=yes", "ProtectHome=read-only"),
            ("DynamicUser=yes", "DynamicUser=no"),
            ("NoNewPrivileges=yes", "NoNewPrivileges=no"),
            ("ExecStart=/usr/bin/false", "ExecStart=/usr/bin/python3"),
            ("RefuseManualStart=yes", "RefuseManualStart=no"),
            ("ConditionPathExists=/run/crypto-yall-readonly-review-never-create",
             "ConditionPathExists=/"),
            ("CapabilityBoundingSet=", "CapabilityBoundingSet=CAP_NET_ADMIN"),
            ("RestrictAddressFamilies=AF_UNIX",
             "RestrictAddressFamilies=AF_UNIX AF_INET"),
            ("MemoryDenyWriteExecute=yes", "MemoryDenyWriteExecute=no"),
        )
        for old, replacement in mutations:
            with self.subTest(key=old):
                self.assertIn(old, source)
                with self.assertRaises(ValueError):
                    inspect_unit(source.replace(old, replacement, 1))

    def test_credentials_mounts_sockets_and_install_hooks_are_rejected(self):
        source = UNIT.read_text("utf-8")
        mutations = (
            "\nEnvironment=HL_PRIVATE_KEY=not-a-real-key\n",
            "\nEnvironmentFile=/etc/default/trading\n",
            "\nLoadCredential=wallet:/etc/keys/wallet\n",
            "\nBindReadOnlyPaths=/home\n",
            "\nReadWritePaths=/tmp\n",
            "\nExecStartPre=/bin/true\n",
            "\nSocketBindAllow=any\n",
            "\nUser=trading\n",
        )
        for addition in mutations:
            with self.subTest(addition=addition):
                with self.assertRaises(ValueError):
                    inspect_unit(source + addition)
        with self.assertRaises(ValueError):
            inspect_unit(source + "\n[Install]\nWantedBy=multi-user.target\n")
        with self.assertRaises(ValueError):
            inspect_unit(source + "\n[Socket]\nListenStream=8888\n")

    def test_duplicate_directive_and_partial_unit_fail_closed(self):
        source = UNIT.read_text("utf-8")
        with self.assertRaises(Exception):
            inspect_unit(source + "\nPrivateNetwork=no\n")
        with self.assertRaises(ValueError):
            inspect_unit(source.replace("ProtectHome=yes\n", "", 1))


if __name__ == "__main__":
    unittest.main()
