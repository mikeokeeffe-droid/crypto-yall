"""Offline-only protected journal interface fixture.

This models a narrow service API with an injected test identity verifier.
It does NOT enforce OS/database permissions, authenticate real workloads,
or provide live exchange capabilities. The underlying journal still has a
direct-call bypass if exposed to untrusted callers.
"""
from dataclasses import dataclass
from offline_bot_identity_fixture import OfflineIdentityVerifier
from offline_sender_restart_journal import OfflineRestartJournal

@dataclass(frozen=True)
class ProtectedFixtureResult:
    state: str
    submit_authorized: bool = False

class OfflineProtectedJournalFixture:
    def __init__(self, *, verifier, journal):
        if type(verifier) is not OfflineIdentityVerifier:
            raise TypeError("offline identity verifier required")
        if type(journal) is not OfflineRestartJournal:
            raise TypeError("offline journal required")
        self._verifier = verifier
        self._journal = journal

    def request_entry(self, *, principal, requested_bot, environment, account,
                      dex, coin):
        identity = self._verifier.verify(
            principal=principal, requested_bot=requested_bot,
            environment=environment, account=account)
        if identity is None:
            return ProtectedFixtureResult("hold")
        try:
            claim = self._journal.reserve(
                bot=identity.bot, environment=environment, account=account,
                dex=dex, coin=coin)
        except (OSError, Exception):
            return ProtectedFixtureResult("hold")
        return ProtectedFixtureResult("reserved" if claim else "hold")

    def request_close(self, **_kwargs):
        # Never infer closing rights from a claim or caller-supplied identity.
        return ProtectedFixtureResult("hold")

    def request_dispatch(self, **_kwargs):
        # This fixture deliberately has no submission pathway.
        return ProtectedFixtureResult("hold")
