"""Identity-gated offline journal admission, never a live sender.

This wrapper is an isolated fixture. Direct journal.reserve remains ungated
and must not be exposed to untrusted workloads or production callers.
"""
from dataclasses import dataclass
from offline_bot_identity_fixture import OfflineIdentityVerifier
from offline_sender_restart_journal import OfflineRestartJournal

@dataclass(frozen=True)
class OfflineAdmissionReview:
    state: str
    claim: tuple | None = None
    submit_authorized: bool = False

def reserve_verified_fixture(*, verifier, journal, principal, requested_bot,
                             environment, account, dex, coin):
    if (type(verifier) is not OfflineIdentityVerifier
            or type(journal) is not OfflineRestartJournal):
        return OfflineAdmissionReview("hold")
    identity = verifier.verify(
        principal=principal, requested_bot=requested_bot,
        environment=environment, account=account)
    if identity is None:
        return OfflineAdmissionReview("hold")
    try:
        claim = journal.reserve(
            bot=identity.bot, environment=environment,
            account=account, dex=dex, coin=coin)
    except (OSError, Exception):
        # This is an offline-only fail-closed fixture, never permission to retry.
        return OfflineAdmissionReview("hold")
    return OfflineAdmissionReview("reserved" if claim else "hold", claim)
