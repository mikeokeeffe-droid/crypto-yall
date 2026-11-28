"""Synthetic-only coordinator dispatch: durable marker before fake effect.

This module is not a service, exchange adapter, signer or trading permission.
It only accepts the exact offline fixture classes. Claim and fake attempt
remain unresolved after every outcome, including an apparently successful fake.
"""
from dataclasses import dataclass

from offline_atomic_coordinator_fixture import OfflineAtomicCoordinator
from offline_shared_sender_prototype import FakeExchange


@dataclass(frozen=True)
class OfflineFakeAttempt:
    state: str
    reason: str
    submit_authorized: bool = False


def simulate_atomic_dispatch_once(*, coordinator, fake, environment, account,
                                  dex, coin, token, fence):
    held = OfflineFakeAttempt("hold", "no fake attempt allowed")
    if (type(coordinator) is not OfflineAtomicCoordinator
            or type(fake) is not FakeExchange):
        return held
    # The coordinator's SQLite compare-and-swap commits dispatch_unknown
    # before the fake exchange can observe an attempt. Once marked, a later
    # process must never automatically repeat the same fake attempt.
    cloid = coordinator.mark_fake_dispatch_unknown(
        environment=environment, account=account, dex=dex, coin=coin,
        token=token, fence=fence,
    )
    if cloid is None:
        return held
    try:
        fake.record_fake_attempt(token, cloid)
    except Exception:
        return OfflineFakeAttempt("hold", "fake result unknown")
    return OfflineFakeAttempt(
        "observed_unverified",
        "synthetic observation only; claim remains dispatch_unknown",
    )
