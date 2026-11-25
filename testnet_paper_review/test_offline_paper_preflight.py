"""Offline no-order preflight regression tests. Never imports live executors."""
import copy
import unittest
from testnet_paper_review import offline_paper_preflight as gate


class PaperPreflightReviewTests(unittest.TestCase):
    def test_profile_is_an_explicit_hold(self):
        profile = gate.load_profile()
        self.assertEqual(profile, gate.EXPECTED_PROFILE)
        self.assertFalse(profile["order_placement_authorized"])
        self.assertFalse(profile["mainnet_authorized"])
        self.assertTrue(gate.check_review_profile(profile))

    def test_any_authority_or_check_change_stays_hold(self):
        for key in ("deployment_authorized", "network_authorized",
                    "order_placement_authorized", "workflow_automation_authorized",
                    "mainnet_authorized"):
            profile = copy.deepcopy(gate.EXPECTED_PROFILE)
            profile[key] = True
            with self.subTest(key=key):
                self.assertTrue(gate.check_review_profile(profile))
        profile = copy.deepcopy(gate.EXPECTED_PROFILE)
        profile["checks"]["independent_security_review"] = "APPROVED"
        self.assertTrue(gate.check_review_profile(profile))

    def test_existing_signing_paths_inventory_is_a_hold(self):
        findings = gate.inspect_repository()
        self.assertTrue(any("Mainnet-selectable" in x for x in findings))
        self.assertTrue(any("signing-key-capable" in x for x in findings))
        self.assertTrue(all(x.startswith("HOLD:") for x in findings))

    def test_exit_is_hold_with_no_trade(self):
        self.assertEqual(gate.main(), 2)


if __name__ == "__main__":
    unittest.main()
