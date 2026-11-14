"""Offline-only signer-free view for each original bot's read/entry boundary.

Combines synthetic, untrusted Info snapshots with request-only entry envelopes.
Does not import original executors, Hyperliquid, networking, a DB, an order SDK,
or credentials. This does NOT replace any live get_client or grant trading.
Bot identity and scope are supplied by a disposable test harness, not verified
production workload authentication. No real exchange provenance is claimed.
"""
from dataclasses import dataclass

from offline_original_bot_intent_adapter import (
    prepare_signer_free_entry_handoff_offline,
)
from offline_signer_free_info_fixture_ci import (
    OfflineSignerFreeInfoScope,
    make_signer_free_info_fixture,
)

_BOTS = frozenset(("daily", "intraday", "aggressive"))


@dataclass(frozen=True)
class OfflineSignerFreeBotView:
    """One read-only Info surface plus a non-authorizing request builder."""
    bot: str
    environment: str
    account: str
    info: object
    submit_authorized: bool = False
    origin_authenticated: bool = False
    ownership_verified: bool = False

    def prepare_entry_request(self, *, trade, rounded_size):
        """Return a request-only envelope or HOLD, never a trade permission."""
        return prepare_signer_free_entry_handoff_offline(
            verified_bot=self.bot,
            trade=trade,
            rounded_size=rounded_size,
            pinned_environment=self.environment,
            pinned_account=self.account,
        )


def make_offline_signer_free_bot_view(
    *, verified_bot, pinned_environment, pinned_account, snapshot,
    pinned_dex="",
):
    """Require a valid harness identity/scope and strictly shaped fake data.

    Return None on any mismatch. No socket, signer, database, key or exchange
    call can be injected. Caller-supplied 'verified_bot' is a CI fixture pin,
    NOT independently authenticated operating-system workload identity.
    """
    if (type(verified_bot) is not str or verified_bot not in _BOTS
            or pinned_dex != ""):
        return None
    info = make_signer_free_info_fixture(
        scope=OfflineSignerFreeInfoScope(
            pinned_environment, pinned_account,
        ),
        snapshot=snapshot,
    )
    if info is None:
        return None
    return OfflineSignerFreeBotView(
        bot=verified_bot,
        environment=pinned_environment,
        account=pinned_account,
        info=info,
    )
