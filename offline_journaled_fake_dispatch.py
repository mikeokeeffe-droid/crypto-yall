"""Offline-only bridge from disposable restart journal to fake recorder.

No trading SDK, signer, HTTP or production credentials. A durable ambiguous
marker precedes the fake side effect; a restart cannot replay it.
"""
from dataclasses import dataclass
from offline_sender_restart_journal import OfflineRestartJournal
from offline_shared_sender_prototype import FakeExchange

@dataclass(frozen=True)
class FakeDispatchReview:
    state: str
    reason: str
    submit_authorized: bool = False

def simulate_journaled_once(*, journal, fake, environment, account, dex, coin,
                            token, fence):
    if type(journal) is not OfflineRestartJournal or type(fake) is not FakeExchange:
        return FakeDispatchReview("hold", "offline fixture types required")
    scope = dict(environment=environment, account=account, dex=dex, coin=coin)
    if type(token) is not str or type(fence) is not int:
        return FakeDispatchReview("hold", "invalid claim identity")
    claim = journal.inspect(**scope)
    if (claim is None or claim[1] != token or claim[3] != fence
            or claim[4] != "reserved"):
        return FakeDispatchReview("hold", "unknown, stale or already attempted claim")
    # The journal atomically transitions only a still-reserved exact claim.
    # A failed commit prevents any fake side effect.
    if not journal.mark_dispatch_unknown(token=token, fence=fence, **scope):
        return FakeDispatchReview("hold", "durable attempt marker not committed")
    try:
        fake.record_fake_attempt(token, claim[2])
    except Exception:
        return FakeDispatchReview("hold", "fake outcome unknown; claim retained")
    return FakeDispatchReview("observed_unverified",
                              "fixture response only; ownership remains unverified")
