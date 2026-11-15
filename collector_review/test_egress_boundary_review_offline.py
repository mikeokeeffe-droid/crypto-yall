"""Offline review only: firewall observations never grant runtime egress."""
import unittest

from collector_review.egress_boundary_review_offline import (
    HostFirewallObservation,
    assess_reported_firewall_offline,
)


def observation(**overrides):
    data = {
        "source": "operator_screenshot",
        "ufw_status": "active",
        "ufw_default_incoming": "deny",
        "ufw_default_outgoing": "allow",
        "nft_ipv4_output_policy": "accept",
        "nft_ipv6_output_policy": "accept",
        "cloud_outbound_scope": "unrestricted",
    }
    data.update(overrides)
    return HostFirewallObservation(**data)


class HostEgressPolicyReviewTests(unittest.TestCase):
    def assert_no_go(self, evidence):
        result = assess_reported_firewall_offline(evidence)
        self.assertEqual(result.state, "hold")
        self.assertFalse(result.actual_runtime_verified)
        self.assertFalse(result.firewall_enforced_for_collector)
        self.assertFalse(result.origin_authenticated)
        self.assertFalse(result.testnet_network_authorized)
        self.assertFalse(result.trading_authorized)
        return result

    def test_reported_host_allows_outbound(self):
        result = self.assert_no_go(observation())
        self.assertTrue(result.observed_outbound_allow)
        self.assertIn("outbound allowed", result.reason)

    def test_apparent_deny_does_not_falsely_prove_enforcement(self):
        for evidence in (
            observation(ufw_default_outgoing="deny",
                        nft_ipv4_output_policy="drop",
                        nft_ipv6_output_policy="drop",
                        cloud_outbound_scope="restricted_unverified"),
            observation(ufw_default_outgoing="unknown",
                        nft_ipv4_output_policy="unknown",
                        nft_ipv6_output_policy="unknown",
                        cloud_outbound_scope="unknown"),
            observation(ufw_status="inactive",
                        ufw_default_outgoing="deny",
                        nft_ipv4_output_policy="drop",
                        nft_ipv6_output_policy="drop",
                        cloud_outbound_scope="unknown"),
        ):
            with self.subTest(evidence=evidence):
                result = self.assert_no_go(evidence)
                self.assertFalse(result.observed_outbound_allow)

    def test_ipv4_ipv6_or_cloud_allow_precludes_restrictive_claim(self):
        for field, value in (
            ("ufw_default_outgoing", "allow"),
            ("nft_ipv4_output_policy", "accept"),
            ("nft_ipv6_output_policy", "accept"),
            ("cloud_outbound_scope", "unrestricted"),
        ):
            data = dict(ufw_default_outgoing="deny",
                        nft_ipv4_output_policy="drop",
                        nft_ipv6_output_policy="drop",
                        cloud_outbound_scope="restricted_unverified")
            data[field] = value
            with self.subTest(field=field):
                result = self.assert_no_go(observation(**data))
                self.assertTrue(result.observed_outbound_allow)

    def test_invalid_or_untrusted_evidence_stays_hold(self):
        self.assert_no_go(None)
        self.assert_no_go({})
        self.assert_no_go(observation(source="untrusted_sender"))
        self.assert_no_go(observation(nft_ipv4_output_policy="ACCEPT"))
        self.assert_no_go(observation(ufw_status="active;enable"))
        self.assert_no_go(observation(cloud_outbound_scope="approved"))


if __name__ == "__main__":
    unittest.main()
