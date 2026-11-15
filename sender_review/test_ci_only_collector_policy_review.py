"""Offline-only negative tests for disabled read-only collector policy."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from sender_review.ci_only_collector_policy_review import (
    POLICY_PATH, audit_checked_in_policy_offline, review_offline_collector_policy
)

UNIT = POLICY_PATH.with_name("ci_only_readonly_collector_review.service")


class CollectorPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = json.loads(POLICY_PATH.read_text("utf-8"))
        cls.unit_bytes = UNIT.read_bytes()

    def check(self, policy, unit=None):
        return review_offline_collector_policy(
            policy_bytes=json.dumps(policy).encode(),
            unit_bytes=self.unit_bytes if unit is None else unit,
        )

    def test_disabled_fixture_is_valid_but_never_authorizes(self):
        result = audit_checked_in_policy_offline()
        self.assertTrue(result.static_policy_valid)
        self.assertEqual(result.state, "HOLD")
        for attr in (
            "host_attested", "runtime_isolated", "network_authorized",
            "exchange_authenticated", "trading_authorized",
        ):
            self.assertFalse(getattr(result, attr))

    def test_any_activation_or_proof_claim_is_denied(self):
        targets = (
            ("enabled", True),
            ("deployment_authorized", True),
            ("proposed_environment", "mainnet"),
            ("synthetic_account", "0x" + "2"*40),
            ("runtime_unit", "/etc/systemd/system/collector.service"),
            ("status", "READY"),
        )
        for key, value in targets:
            p = deepcopy(self.policy); p[key] = value
            with self.subTest(key=key):
                self.assertFalse(self.check(p).static_policy_valid)
        for key in self.policy["runtime_proof"]:
            p = deepcopy(self.policy); p["runtime_proof"][key] = True
            with self.subTest(proof=key):
                self.assertFalse(self.check(p).static_policy_valid)
        for key in self.policy["runtime_network"]:
            p = deepcopy(self.policy); p["runtime_network"][key] = True
            with self.subTest(network=key):
                self.assertFalse(self.check(p).static_policy_valid)
        for key in self.policy["operator_gate"]:
            p = deepcopy(self.policy); p["operator_gate"][key] = True
            with self.subTest(operator=key):
                self.assertFalse(self.check(p).static_policy_valid)

    def test_any_secret_role_or_credential_mount_is_denied(self):
        for key in self.policy["credential_boundary"]:
            p = deepcopy(self.policy)
            p["credential_boundary"][key] = ["HL_PRIVATE_KEY"]
            with self.subTest(key=key):
                self.assertFalse(self.check(p).static_policy_valid)

    def test_egress_expansion_and_endpoint_changes_are_denied(self):
        variations = (
            ("transport", "http"),
            ("hostname", "api.hyperliquid.xyz"),
            ("hostname", "attacker.example"),
            ("port", 80),
            ("port", True),
            ("path", "/exchange"),
            ("http_method", "GET"),
            ("request_type_allowlist", ["exchange"]),
            ("request_type_allowlist", ["clearinghouseState"]),
            ("allow_http_redirects", True),
            ("allow_arbitrary_dns", True),
            ("allow_proxy_inheritance", True),
            ("allow_exchange_mutations", True),
            ("granted_to_runtime", True),
        )
        for key, value in variations:
            p = deepcopy(self.policy)
            p["future_readonly_target_review_only"][key] = value
            with self.subTest(key=key):
                self.assertFalse(self.check(p).static_policy_valid)

    def test_unknown_fields_duplicate_json_and_unit_changes_denied(self):
        p = deepcopy(self.policy); p["unexpected"] = "true"
        self.assertFalse(self.check(p).static_policy_valid)
        p = deepcopy(self.policy); p["credential_boundary"]["extra"] = []
        self.assertFalse(self.check(p).static_policy_valid)
        self.assertFalse(review_offline_collector_policy(
            policy_bytes=b'{"enabled":false,"enabled":true}',
            unit_bytes=self.unit_bytes,
        ).static_policy_valid)
        changed = self.unit_bytes.replace(
            b"PrivateNetwork=yes", b"PrivateNetwork=no"
        )
        self.assertFalse(self.check(self.policy, changed).static_policy_valid)
        self.assertFalse(self.check(self.policy, b"").static_policy_valid)

    def test_source_only_and_no_deployment_path(self):
        source = Path(__file__).with_name(
            "ci_only_collector_policy_review.py").read_text("utf-8")
        import ast
        tree = ast.parse(source)
        modules = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                modules.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                modules.add(n.module)
        self.assertEqual(modules, {"dataclasses", "json", "pathlib",
            "sender_review.test_ci_only_readonly_collector_service"})


if __name__ == "__main__":
    unittest.main()
