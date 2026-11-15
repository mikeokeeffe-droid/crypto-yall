"""Review-only host evidence REQUEST, not host inspection.

Generates a conservative manual read-only worksheet for the operator and an
independent reviewer. The commands are STRINGS, never executed here. Does not
connect to a host, invoke systemctl, inspect secrets, or approve deployment.

The named pre-existing service is a review target, NOT the inert systemd
fixture added by PR #42. No claim is made that it is running or isolated.
"""
from dataclasses import dataclass

SERVICE_NAME = "testnet-collector-offline-review.service"

@dataclass(frozen=True)
class HostEvidenceItem:
    id: str
    purpose: str
    read_only_command: str | None
    assessment: str = "NOT_COLLECTED"
    reviewer_verified: bool = False
    approved_for_deployment: bool = False

@dataclass(frozen=True)
class HostEvidenceRequest:
    status: str
    target_service: str
    evidence: tuple[HostEvidenceItem, ...]
    verified_on_actual_host: bool = False
    independent_security_approval: bool = False
    testnet_network_approval: bool = False
    live_trading_approval: bool = False
    safe_to_deploy: bool = False
    safe_to_trade: bool = False

# Restrict to specifically chosen NON-SECRET systemd properties.
# No raw environment, credential source values, journal entries, process
# arguments, API tokens or private key material are requested.
_SANDBOX_PROPERTIES = (
    "Id", "LoadState", "ActiveState", "SubState", "UnitFileState",
    "DynamicUser", "NoNewPrivileges", "PrivateNetwork",
    "RestrictAddressFamilies", "IPAddressDeny", "IPAddressAllow",
    "ProtectSystem", "ProtectHome", "PrivateDevices",
    "PrivateTmp", "PrivateUsers", "ProtectProc", "ProcSubset",
    "CapabilityBoundingSet", "AmbientCapabilities",
    "ReadWritePaths", "StateDirectory", "RuntimeDirectory",
)
def _show_properties():
    return "systemctl show " + SERVICE_NAME + " " + " ".join(
        "-p " + name for name in _SANDBOX_PROPERTIES
    ) + " --no-pager"

def make_host_evidence_request_offline():
    return HostEvidenceRequest(
        status="NO_GO_UNATTESTED",
        target_service=SERVICE_NAME,
        evidence=(
            HostEvidenceItem(
                "target_commit", "Record exact PR commit SHA and host artifact hash; independent reviewer must compare them",
                None,
            ),
            HostEvidenceItem(
                "unit_properties", "Record specifically allowlisted systemd properties; no secret values",
                _show_properties(),
            ),
            HostEvidenceItem(
                "unit_security", "Collect systemd's assessment of the named unit (not proof of network isolation)",
                "systemd-analyze security --no-pager " + SERVICE_NAME,
            ),
            HostEvidenceItem(
                "host_egress", "Independent security reviewer verifies firewall/proxy, DNS, TLS and real outbound network policy without sharing credentials",
                None,
            ),
            HostEvidenceItem(
                "host_credentials", "Independent reviewer inspects effective identity, secret exposure and writable DB roles using redacted private evidence",
                None,
            ),
            HostEvidenceItem(
                "real_authentication", "Independent reviewer verifies live OIDC issuer, request binding and replay recovery",
                None,
            ),
            HostEvidenceItem(
                "real_exchange_history", "Independent reviewer verifies read-only authenticated order/fill/position origin and older history coverage",
                None,
            ),
            HostEvidenceItem(
                "legacy_cutover", "Independent reviewer verifies all five original execution paths cannot sign or submit concurrently",
                None,
            ),
            HostEvidenceItem(
                "risk_recovery", "Independent reviewer verifies safe reduce-only emergency exits, unknown ACK, outage recovery and rollback",
                None,
            ),
            HostEvidenceItem(
                "independent_approval", "Separate signed testnet and production authorizations must be obtained later",
                None,
            ),
        ),
    )
