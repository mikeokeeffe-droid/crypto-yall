"""Pure Daily-strategy signal adapter for the future isolated SOL TESTNET trial.

This is deliberately NOT a trading strategy or runner: it does not fetch
market prices, import Hyperliquid, use keys, or submit orders. It validates
source-file provenance and a completed SOL daily-bar entry signal produced by
the *existing* Daily model. Only a new entry can become a review candidate;
hold_long/hold_short/exit/flat are blocked. All candidates remain no-trade.

NOTE: A real runtime still must independently prove which bar was used, the
provenance of data, the account state and exclusive durable order ownership.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import math

from signal_utils import classify_signal

ROOT = Path(__file__).resolve().parents[1]
REVIEWED_BLOBS = {
    "strategy.py": "4f927f235b0fc6a8182c701de6ef6c75a3fea31e",
    "signal_utils.py": "8847b9a002fc221826fd6a280cb3ab8cf7753405",
    "hyperliquid_executor.py": "d98cba6e73507192f5155dfd7f2e414dddc7fcb4",
}
SOURCE_TAG = "PINNED_LEGACY_DAILY_REVIEW"
BAR_SECONDS = 24 * 3600
MAX_BAR_LAG_S = 48 * 3600
MAX_COMPUTATION_LAG_S = 15


class SignalReviewHold(ValueError):
    """A disallowed entry signal never authorizes a trade."""


@dataclass(frozen=True)
class DailyTestnetCandidate:
    coin: str
    action: str
    mode: str
    observed_at_s: int
    closed_bar_at_s: int
    bar_id: str
    trial_leverage: int = 1
    source: str = SOURCE_TAG

    @property
    def may_submit(self):
        return False

    def admission_signal(self):
        # Compatible with the separate pure admission checker. This conversion
        # is only a data shape; admission and signature authority remain HOLD.
        return {
            "coin": self.coin,
            "action": self.action,
            "mode": self.mode,
            "observed_at_s": self.observed_at_s,
            "closed_bar_at_s": self.closed_bar_at_s,
            "bar_id": self.bar_id,
        }


def verify_original_daily_sources():
    """Require exact reviewed Git blob contents, without importing executors."""
    for rel, expected in REVIEWED_BLOBS.items():
        path = ROOT / rel
        if not path.is_file() or path.is_symlink():
            raise SignalReviewHold("HOLD: Daily strategy source missing or redirected")
        payload = path.read_bytes()
        sha = hashlib.sha1(
            b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
        ).hexdigest()
        if sha != expected:
            raise SignalReviewHold("HOLD: Daily strategy source changed; re-review required")
    return "HOLD: pinned Daily source inspected; not trading authorization"


def review_daily_signal(*, ticker, last_signal, prior_signal, regime,
                        action, bar_started_at_s, observed_at_s, now_s,
                        legacy_leverage):
    """Map a *new*, completed Daily SOL signal to a Testnet review candidate."""
    verify_original_daily_sources()
    if ticker != "SOL-USD":
        raise SignalReviewHold("HOLD: only SOL daily entry is in Testnet review")
    if (type(last_signal) is not int or type(prior_signal) is not int
            or last_signal not in (-1, 0, 1)
            or prior_signal not in (-1, 0, 1)):
        raise SignalReviewHold("HOLD: invalid Daily signal states")
    if regime not in ("Bull", "Chop", "Bear"):
        raise SignalReviewHold("HOLD: invalid Daily regime")
    classified = classify_signal(last_signal, prior_signal, regime)
    if action != classified or classified not in ("buy", "enter_short"):
        raise SignalReviewHold("HOLD: not a verified new Daily SOL entry")
    if (classified == "buy" and regime == "Bear") or (
            classified == "enter_short" and regime == "Bull"):
        raise SignalReviewHold("HOLD: entry conflicts with Daily regime")
    if type(legacy_leverage) not in (int, float) \
            or not math.isfinite(legacy_leverage) or legacy_leverage <= 0:
        raise SignalReviewHold("HOLD: invalid legacy leverage suggestion")
    # The original aggressive Daily leverage is NEVER passed through:
    # all initial Testnet plans remain exactly 1x.
    if any(type(x) is not int for x in
           (bar_started_at_s, observed_at_s, now_s)):
        raise SignalReviewHold("HOLD: missing or invalid market evidence times")
    if bar_started_at_s <= 0 or bar_started_at_s % BAR_SECONDS != 0:
        raise SignalReviewHold("HOLD: unverified UTC daily candle boundary")
    closed_bar_at_s = bar_started_at_s + BAR_SECONDS
    if (closed_bar_at_s > observed_at_s
            or not 0 <= observed_at_s - closed_bar_at_s <= MAX_BAR_LAG_S):
        raise SignalReviewHold("HOLD: unfinished or stale Daily candle")
    if not 0 <= now_s - observed_at_s <= MAX_COMPUTATION_LAG_S:
        raise SignalReviewHold("HOLD: stale or future signal computation")
    from datetime import datetime, timezone
    bar_id = datetime.fromtimestamp(
        bar_started_at_s, tz=timezone.utc
    ).strftime("%Y-%m-%d")
    return DailyTestnetCandidate(
        coin="SOL", action=classified, mode="OFFLINE_SIGNAL_REVIEW",
        observed_at_s=observed_at_s, closed_bar_at_s=closed_bar_at_s,
        bar_id=bar_id
    )
