"""Offline static policy review; cannot activate networking or trading."""
from dataclasses import dataclass
import json
from pathlib import Path

POLICY_PATH = Path(__file__).with_name("ci_only_collector_credentials_egress_policy.json")
EXPECTED_ACCOUNT = "0x" + "1" * 40
EXPECTED_TYPES = (
    "clearinghouseState", "openOrders", "historicalOrders",
    "userFillsByTime", "orderStatus",
)
PROOF_KEYS = (
    "os_isolation_verified", "firewall_egress_verified",
    "tls_peer_verified", "dns_and_proxy_policy_verified",
    "runtime_secret_absence_verified", "historical_completeness_verified",
)
SECRET_KEYS = (
    "accepted_secret_names", "environment_file_paths",
    "credential_mount_paths", "private_key_refs", "db_writable_roles",
    "inherited_service_credentials",
)
OPERATOR_KEYS = (
    "independent_security_review_approved",
    "approved_host_attestation_present",
    "testnet_connectivity_approved", "mainnet_trading_approved",
)


@dataclass(frozen=True)
class OfflineIsolationDecision:
    state: str = "HOLD"
    reason: str = "not deployable"
    static_policy_valid: bool = False
    host_attested: bool = False
    runtime_isolated: bool = False
    network_authorized: bool = False
    exchange_authenticated: bool = False
    trading_authorized: bool = False


def _unique_object(pairs):
    d = {}
    for key, value in pairs:
        if key in d:
            raise ValueError("duplicate JSON property")
        d[key] = value
    return d


def review_offline_collector_policy(*, policy_bytes, unit_bytes):
    hold = OfflineIsolationDecision()
    if type(policy_bytes) is not bytes or not 0 < len(policy_bytes) <= 16384:
        return hold
    if type(unit_bytes) is not bytes or not 0 < len(unit_bytes) <= 16384:
        return hold
    try:
        policy = json.loads(policy_bytes.decode("utf-8"), object_pairs_hook=_unique_object)
        from sender_review.test_ci_only_readonly_collector_service import inspect_unit
        unit = unit_bytes.decode("utf-8")
        inspect_unit(unit)
    except (ValueError, TypeError, UnicodeError):
        return hold
    if type(policy) is not dict or set(policy) != {
        "schema_version", "status", "enabled", "deployment_authorized",
        "proposed_environment", "synthetic_account", "runtime_unit",
        "runtime_proof", "runtime_network", "credential_boundary",
        "future_readonly_target_review_only", "operator_gate",
    }:
        return hold
    if (type(policy["schema_version"]) is not int or policy["schema_version"] != 1
        or policy["status"] != "DRAFT_OFFLINE_ONLY_NO_GO"
        or policy["enabled"] is not False
        or policy["deployment_authorized"] is not False
        or policy["proposed_environment"] != "testnet"
        or policy["synthetic_account"] != EXPECTED_ACCOUNT
        or policy["runtime_unit"] != "sender_review/ci_only_readonly_collector_review.service"):
        return hold
    proof = policy["runtime_proof"]
    net = policy["runtime_network"]
    credentials = policy["credential_boundary"]
    endpoint = policy["future_readonly_target_review_only"]
    operator = policy["operator_gate"]
    if (type(proof) is not dict or set(proof) != set(PROOF_KEYS)
        or any(proof[key] is not False for key in PROOF_KEYS)
        or type(net) is not dict or set(net) != {
            "enabled", "outbound_tcp_allowed", "listen_sockets_allowed"
        } or any(v is not False for v in net.values())
        or type(credentials) is not dict or set(credentials) != set(SECRET_KEYS)
        or any(type(credentials[k]) is not list or credentials[k] for k in SECRET_KEYS)
        or type(operator) is not dict or set(operator) != set(OPERATOR_KEYS)
        or any(operator[k] is not False for k in OPERATOR_KEYS)):
        return hold
    if type(endpoint) is not dict or set(endpoint) != {
        "transport", "hostname", "port", "path", "http_method",
        "request_type_allowlist", "allow_http_redirects", "allow_arbitrary_dns",
        "allow_proxy_inheritance", "allow_exchange_mutations", "granted_to_runtime"
    }:
        return hold
    if (endpoint["transport"] != "https"
        or endpoint["hostname"] != "api.hyperliquid-testnet.xyz"
        or type(endpoint["port"]) is not int or endpoint["port"] != 443
        or endpoint["path"] != "/info" or endpoint["http_method"] != "POST"
        or type(endpoint["request_type_allowlist"]) is not list
        or endpoint["request_type_allowlist"] != list(EXPECTED_TYPES)
        or any(endpoint[key] is not False for key in (
            "allow_http_redirects", "allow_arbitrary_dns", "allow_proxy_inheritance",
            "allow_exchange_mutations", "granted_to_runtime"
        ))):
        return hold
    return OfflineIsolationDecision(
        reason="static disabled fixture coherent; NO runtime evidence or approval",
        static_policy_valid=True,
    )


def audit_checked_in_policy_offline():
    unit_path = POLICY_PATH.with_name("ci_only_readonly_collector_review.service")
    return review_offline_collector_policy(
        policy_bytes=POLICY_PATH.read_bytes(), unit_bytes=unit_path.read_bytes()
    )
