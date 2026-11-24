"""Offline ONLY Testnet egress contract review; never creates network sockets.

This validates a proposed JSON policy and synthetic request frames. It is NOT
a gateway, firewall, proxy, runtime permission, or approval to make requests.
"""
import json
from pathlib import Path

POLICY_PATH = Path(__file__).with_name("testnet_egress_policy_review_only.json")
FIXED_ACCOUNT = "0xF14348Bdf59BA186F9CdD0fC5F369e1f6D3b7dC0"
TYPES = ("clearinghouseState", "openOrders")
URL = ("https", "api.hyperliquid-testnet.xyz", 443, "POST", "/info")


class PolicyHold(ValueError):
    pass


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PolicyHold("duplicate JSON field")
        result[key] = value
    return result


def policy_contract(policy):
    """Accept the exact, disabled review contract only."""
    if not isinstance(policy, dict) or set(policy) != {
        "schema_version", "label", "status", "network_authorized",
        "gateway_implemented", "automatic_execution", "deployable_as_is",
        "credential_access_authorized", "order_execution_authorized",
        "mainnet_access_authorized", "proposed_runner", "proposed_gateway"
    }:
        raise PolicyHold("invalid review contract")
    for key in ("network_authorized", "gateway_implemented",
                "automatic_execution", "deployable_as_is",
                "credential_access_authorized", "order_execution_authorized",
                "mainnet_access_authorized"):
        if policy[key] is not False:
            raise PolicyHold("network/trading cannot be enabled by this contract")
    if policy["schema_version"] != 1 or policy["status"] != "HOLD_NO_TESTNET_NETWORK_AUTHORIZATION":
        raise PolicyHold("review status changed")
    runner = policy["proposed_runner"]
    if (not isinstance(runner, dict)
        or runner != {
            "user": "readonlycheck", "require_transient_unit": True,
            "direct_network": "deny", "no_new_privileges": True,
            "readonly_code": True, "allow_signing_credentials": False,
            "allow_production_database": False,
            "allow_privileged_unix_sockets": False
        }):
        raise PolicyHold("runner isolation proposal drift")
    gateway = policy["proposed_gateway"]
    expected = {
        "separate_identity": True, "independently_reviewed": True,
        "destination": {
            "scheme": URL[0], "host": URL[1], "port": URL[2],
            "method": URL[3], "path": URL[4]
        },
        "allow_arbitrary_urls": False, "allow_redirects": False,
        "allow_connect_proxy": False, "allow_exchange_endpoint": False,
        "require_certificate_validation": True,
        "require_hostname_validation": True,
        "public_account": FIXED_ACCOUNT,
        "request_types": list(TYPES),
        "request_dex": "", "max_requests_per_run": 2,
        "max_requests_per_type": 1, "max_response_bytes": 524288,
        "timeout_seconds_per_request": 8, "deny_retries": True,
        "require_exact_request_json": True, "fail_closed": True
    }
    if not isinstance(gateway, dict) or gateway != expected:
        raise PolicyHold("gateway policy proposal drift")
    return True


def inspect_synthetic_requests(policy, requests):
    """Validate synthetic ordered frames only. No networking exists here."""
    policy_contract(policy)
    if not isinstance(requests, list) or len(requests) != 2:
        raise PolicyHold("exactly two synthetic frames required")
    for frame, request_type in zip(requests, TYPES):
        if not isinstance(frame, dict) or set(frame) != {"scheme", "host", "port", "method", "path", "body"}:
            raise PolicyHold("invalid synthetic frame")
        if tuple(frame[key] for key in ("scheme", "host", "port", "method", "path")) != URL:
            raise PolicyHold("synthetic destination not approved")
        try:
            raw = frame["body"]
            if not isinstance(raw, str) or len(raw) > 256:
                raise PolicyHold("invalid synthetic JSON body")
            body = json.loads(raw, object_pairs_hook=_unique_pairs)
        except (ValueError, TypeError):
            raise PolicyHold("invalid synthetic JSON body") from None
        if not isinstance(body, dict) or body != {
            "type": request_type, "user": FIXED_ACCOUNT, "dex": ""
        } or set(body) != {"type", "user", "dex"}:
            raise PolicyHold("unapproved synthetic request body")
    return True


def load_review_contract():
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
