"""Offline deployment-readiness manifest review: always NO-GO.

This code examines a review-only JSON artifact and the inert systemd fixture.
It cannot attest a host, approve code, authenticate an operator, deploy,
request exchange data, sign or submit an order. No asserted manifest value
can change its decision to GO; observed drift fails closed.
"""
from dataclasses import dataclass
import json
from pathlib import Path

MANIFEST = Path(__file__).with_name("ci_only_deployment_readiness_manifest.json")
EXPECTED_IDS = (
    "runtime_oidc", "request_integrity", "sender_db_roles",
    "runtime_isolation", "collector_transport", "archive_provenance",
    "ownership_reconcile", "single_writer", "exit_reliability",
    "unknown_ack_recovery", "observability_rollback",
    "independent_security_review", "testnet_operator_approval",
    "production_operator_approval",
)
EXPECTED_OWNERS = {
    "runtime_oidc": "security",
    "request_integrity": "security",
    "sender_db_roles": "security",
    "runtime_isolation": "operations",
    "collector_transport": "security",
    "archive_provenance": "data",
    "ownership_reconcile": "risk",
    "single_writer": "security",
    "exit_reliability": "risk",
    "unknown_ack_recovery": "risk",
    "observability_rollback": "operations",
    "independent_security_review": "approval",
    "testnet_operator_approval": "approval",
    "production_operator_approval": "approval",
}
DENIED_FLAGS = (
    "may_merge", "may_deploy_testnet", "may_deploy_production",
    "may_connect_exchange", "may_sign_or_submit_orders",
    "ci_success_is_deployment_approval", "operator_approval_obtained",
    "security_approval_obtained", "runtime_host_attested",
)
EXPECTED_GLOBAL = {
    "schema_version": 1,
    "artifact": "PROTECTED_SENDER_DEPLOYMENT_READINESS_REVIEW_ONLY",
    "review_pr": 42,
    "repository": "mikeokeeffe-droid/crypto-yall",
    "review_branch": "review/protected-sender-cutover-20261115",
    "verified_scope": "offline source and disposable CI tests only; not an operational attestation",
    "global_decision": "NO_GO",
}
EXPECTED_FIELDS = set(EXPECTED_GLOBAL) | set(DENIED_FLAGS) | {"gates"}
GATE_FIELDS = {
    "id", "owner", "requirement", "required_evidence", "status",
    "evidence_reference", "reviewer", "approved_commit",
}


@dataclass(frozen=True)
class ReadinessResult:
    decision: str = "NO_GO"
    reason: str = "independent deployment evidence not verified"
    manifest_valid: bool = False
    independent_host_verified: bool = False
    security_approved: bool = False
    testnet_authorized: bool = False
    production_authorized: bool = False
    deploy_allowed: bool = False
    trade_allowed: bool = False


def _strict_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON key")
        obj[key] = value
    return obj


def review_readiness_bytes(*, manifest_bytes):
    hold = ReadinessResult()
    if type(manifest_bytes) is not bytes or not 0 < len(manifest_bytes) <= 65536:
        return hold
    try:
        value = json.loads(manifest_bytes.decode("utf-8"),
                           object_pairs_hook=_strict_object)
    except (UnicodeError, ValueError, TypeError):
        return hold
    if type(value) is not dict or set(value) != EXPECTED_FIELDS:
        return hold
    for key, expected in EXPECTED_GLOBAL.items():
        if type(value.get(key)) is not type(expected) or value[key] != expected:
            return hold
    if any(value.get(key) is not False for key in DENIED_FLAGS):
        return hold
    gates = value.get("gates")
    if type(gates) is not list or len(gates) != len(EXPECTED_IDS):
        return hold
    ids = []
    for gate in gates:
        if type(gate) is not dict or set(gate) != GATE_FIELDS:
            return hold
        id_value = gate["id"]
        if type(id_value) is not str or id_value not in EXPECTED_OWNERS:
            return hold
        if gate["owner"] != EXPECTED_OWNERS[id_value]:
            return hold
        if (type(gate["requirement"]) is not str
            or len(gate["requirement"]) < 20
            or type(gate["required_evidence"]) is not str
            or len(gate["required_evidence"]) < 20
            or gate["status"] != "UNVERIFIED"
            or gate["evidence_reference"] is not None
            or gate["reviewer"] is not None
            or gate["approved_commit"] is not None):
            return hold
        ids.append(id_value)
    if tuple(ids) != EXPECTED_IDS:
        return hold
    return ReadinessResult(
        reason="review-only manifest structurally sound; all 14 gates UNVERIFIED",
        manifest_valid=True,
    )


def inspect_checked_in_readiness():
    return review_readiness_bytes(manifest_bytes=MANIFEST.read_bytes())
