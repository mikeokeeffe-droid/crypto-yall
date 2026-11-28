"""Offline identity-verification fixture. Not production authentication.

Identity is derived from a trusted test verifier, never from a caller's bot
string. No credentials, SDK, network, trading or order submission.
"""
from dataclasses import dataclass

_BOTS = frozenset(("daily", "intraday", "aggressive"))

@dataclass(frozen=True)
class VerifiedFixtureIdentity:
    bot: str
    environment: str
    account: str

class OfflineIdentityVerifier:
    """A fixed, in-memory verifier mapping opaque test principals to scopes."""
    def __init__(self, identities):
        self._identities = dict(identities)

    def verify(self, *, principal, requested_bot, environment, account):
        # Fixture principal is an injected test assertion, NOT a real credential.
        if type(principal) is not str or type(requested_bot) is not str:
            return None
        identity = self._identities.get(principal)
        if (type(identity) is not VerifiedFixtureIdentity
                or identity.bot not in _BOTS
                or identity.bot != requested_bot
                or identity.environment != environment
                or identity.account != account):
            return None
        return identity
