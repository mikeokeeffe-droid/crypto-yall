"""Review-only collector runtime identity and secret-isolation preflight.

This module neither opens a network connection nor reads secret VALUES.
It evaluates an explicitly supplied snapshot of the prospective runtime.
Passing is at most a *candidate* for further OS-level audit. It is NEVER
evidence of enforced egress isolation, authenticated data provenance,
approval to access a testnet account, or permission to trade.
"""
from dataclasses import dataclass
import re

_SENSITIVE_ENV = re.compile(
    r"(?:^|_)(?:PRIVATE_KEY|SECRET|SEED|MNEMONIC|"
    r"API_KEY|ACCESS_KEY|SIGNING_KEY|TOKEN)(?:$|_)",
    re.IGNORECASE,
)
# A deliberately small, illustrative environment allowlist. Any other
# variable needs a separate, explicit runtime/credential review. No values
# are evaluated, copied, recorded or logged.
_ALLOWED_ENV_NAMES = frozenset((
    "PATH", "HOME", "LANG", "LC_ALL", "TZ",
    "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE",
))


@dataclass(frozen=True)
class CollectorRuntimeReview:
    state: str = "hold"
    reason: str = "runtime isolation not verified"
    isolated_identity_candidate: bool = False
    credential_names_clear: bool = False
    network_egress_verified: bool = False
    origin_authenticated: bool = False
    trading_authorized: bool = False


def inspect_runtime_identity_offline(*, effective_uid, effective_gid,
                                     environment_names,
                                     expected_uid, expected_gid,
                                     isolated_service_confirmed=False):
    """Review caller-supplied identity metadata; cannot verify the caller.

    Caller claims of service isolation are informational, not proof of OS
    namespaces, egress firewall, file ACLs, process privilege or provenance.
    """
    def hold(reason):
        return CollectorRuntimeReview(reason=reason)

    if (type(effective_uid) is not int or effective_uid <= 0
            or type(effective_gid) is not int or effective_gid <= 0
            or type(expected_uid) is not int or expected_uid <= 0
            or type(expected_gid) is not int or expected_gid <= 0
            or effective_uid != expected_uid or effective_gid != expected_gid):
        return hold("root, unknown or mismatched service identity")

    if (type(environment_names) not in (tuple, list, frozenset)
            or len(environment_names) > 256
            or any(type(name) is not str or not name
                   for name in environment_names)):
        return hold("invalid environment-name metadata")
    if len(set(environment_names)) != len(environment_names):
        return hold("duplicate environment variable names")
    # Refuse any unexpected credentials or unreviewed variables, without
    # reading, printing or persisting a secret value.
    if any(_SENSITIVE_ENV.search(name) for name in environment_names):
        return hold("secret-bearing environment variable name detected")
    if any(name not in _ALLOWED_ENV_NAMES for name in environment_names):
        return hold("unreviewed environment variable name detected")
    if isolated_service_confirmed is not True:
        return hold("dedicated service isolation not independently confirmed")

    return CollectorRuntimeReview(
        state="review_only",
        reason="caller-supplied identity and environment names fit policy; "
               "effective isolation and network egress require OS-level proof",
        isolated_identity_candidate=True,
        credential_names_clear=True,
    )
