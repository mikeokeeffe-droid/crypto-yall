"""Strict OFFLINE review of operator-reported host firewall evidence.

This evaluates untrusted *observations*, not effective kernel policy. It cannot
verify firewall enforcement, isolate a running process, open a socket, or
grant testnet/live approval. It intentionally has NO 'pass' verdict.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class HostFirewallObservation:
    source: str
    ufw_status: str
    ufw_default_incoming: str
    ufw_default_outgoing: str
    nft_ipv4_output_policy: str
    nft_ipv6_output_policy: str
    cloud_outbound_scope: str


@dataclass(frozen=True)
class HostEgressReview:
    state: str = "hold"
    reason: str = "host network egress not independently proven"
    observed_outbound_allow: bool = False
    actual_runtime_verified: bool = False
    firewall_enforced_for_collector: bool = False
    origin_authenticated: bool = False
    testnet_network_authorized: bool = False
    trading_authorized: bool = False


_ALLOWED = {
    "ufw_status": frozenset(("active", "inactive", "unknown")),
    "ufw_default_incoming": frozenset(("allow", "deny", "reject", "unknown")),
    "ufw_default_outgoing": frozenset(("allow", "deny", "reject", "unknown")),
    "nft_ipv4_output_policy": frozenset(("accept", "drop", "unknown")),
    "nft_ipv6_output_policy": frozenset(("accept", "drop", "unknown")),
    "cloud_outbound_scope": frozenset(("unrestricted", "restricted_unverified", "unknown")),
}


def assess_reported_firewall_offline(observation):
    """Classify *reported* evidence and ALWAYS hold independent egress approval.

    Even apparent default drops do not prove a source namespace/cgroup is
    bound to the effective policy, or exclude exceptions, proxies, tunnels,
    direct socket use, DNS, cloud routes, etc.
    """
    if type(observation) is not HostFirewallObservation:
        return HostEgressReview(reason="missing or invalid observed firewall evidence")
    if observation.source != "operator_screenshot":
        return HostEgressReview(reason="firewall observation origin not pinned")
    for field, options in _ALLOWED.items():
        value = getattr(observation, field)
        if type(value) is not str or value not in options:
            return HostEgressReview(reason="invalid or unrecognized firewall observation")
    outgoing_allow = (
        observation.ufw_default_outgoing == "allow"
        or observation.nft_ipv4_output_policy == "accept"
        or observation.nft_ipv6_output_policy == "accept"
        or observation.cloud_outbound_scope == "unrestricted"
    )
    if outgoing_allow:
        return HostEgressReview(
            reason="outbound allowed in reported policy; independent collector egress restriction outstanding",
            observed_outbound_allow=True,
        )
    return HostEgressReview(
        reason="apparent restrictive defaults still cannot prove effective runtime firewall or bypass resistance",
    )
