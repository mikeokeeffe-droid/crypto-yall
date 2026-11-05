"""Offline-only coordinator request boundary simulation.

The client facade has no journal reference or path. A server-side fixture
receives requests and derives the bot from a synthetic verified principal.
This is NOT a real process, network, OS ACL, or authentication boundary.
No SDK, exchange, credentials or dispatch/close capability.
"""
from dataclasses import dataclass
from offline_protected_journal_fixture import OfflineProtectedJournalFixture, ProtectedFixtureResult

@dataclass(frozen=True)
class OfflineEntryIntent:
    requested_bot: str
    environment: str
    account: str
    dex: str
    coin: str

class OfflineCoordinatorServerFixture:
    def __init__(self, protected):
        if type(protected) is not OfflineProtectedJournalFixture:
            raise TypeError("protected fixture required")
        self._protected = protected

    def handle(self, *, principal, operation, intent=None):
        if operation != "request_entry" or type(intent) is not OfflineEntryIntent:
            return ProtectedFixtureResult("hold")
        return self._protected.request_entry(
            principal=principal, requested_bot=intent.requested_bot,
            environment=intent.environment, account=intent.account,
            dex=intent.dex, coin=intent.coin)

class OfflineCoordinatorClientFixture:
    """Restricted client API; never supplies a journal object to callers."""
    def __init__(self, *, send, principal):
        if not callable(send):
            raise TypeError("send callback required")
        self._send = send
        self._principal = principal

    def request_entry(self, intent):
        if type(intent) is not OfflineEntryIntent:
            return ProtectedFixtureResult("hold")
        try:
            return self._send(
                principal=self._principal, operation="request_entry", intent=intent)
        except Exception:
            return ProtectedFixtureResult("hold")

    def request_close(self, **_kwargs):
        return ProtectedFixtureResult("hold")

    def request_dispatch(self, **_kwargs):
        return ProtectedFixtureResult("hold")
