"""Read the REAL pinned Daily SOL model without any execution capabilities.

A new SOL long can be a RESEARCH / HUMAN-REVIEW candidate, never an order.
The original Daily SOL asset profile has allow_short=False, so this module
does not propose a SOL short even if a generic paper fixture supports shorts.

This intentionally recomputes the original Daily indicators, causal HMM regime
and strategy from yfinance history on the previous completed UTC daily candle.
It does NOT import the legacy executor, create an Exchange, load signing keys,
read Gists, write databases, change leverage, or send an order. It may download
public historical market data. If a day is missing, stale or not fully closed,
everything is HOLD; the bot must never guess a signal.

Requires the original project's numpy/pandas/scipy/hmmlearn/scikit-learn/
yfinance dependencies in the dedicated review venv, not any trading secrets.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

from testnet_paper_review.daily_testnet_signal_adapter import (
    verify_original_daily_sources, review_daily_signal,
    SignalReviewHold, ROOT
)
from signal_utils import classify_signal

TICKER="SOL-USD"
DATA_BLOB_IDS={
    "data_loader.py":"4fbb726a6636e419e01fe1133c90652e68b96907",
    "indicators.py":"085bafd169513a371eae147ff71ec8df482ff4c0",
    "hmm_engine.py":"1cccb4bff20b20573cef0b7dc96cfa4b811485ec",
    "backtester.py":"04642c1a41696bb85004767ce85a994a274c7d87",
}
MIN_HISTORY_DAYS=400


class DailySignalEvidenceHold(RuntimeError):
    pass


@dataclass(frozen=True)
class DailySolObservation:
    ticker: str
    daily_bar_utc: str
    regime: str
    last_signal: int
    prior_signal: int
    action: str
    legacy_leverage: str
    trial_leverage: int = 1
    original_daily_source_verified: bool = True
    is_new_daily_sol_buy: bool = False
    may_send: bool = False
    status: str = "NO_NEW_SOL_DAILY_ENTRY_HOLD"


def verify_readonly_daily_model_sources():
    """Pin all actual model/data/profile sources; do not import live executor."""
    verify_original_daily_sources()
    for rel, expected in DATA_BLOB_IDS.items():
        p=ROOT / rel
        if not p.is_file() or p.is_symlink():
            raise DailySignalEvidenceHold("HOLD: model source missing or symlinked")
        raw=p.read_bytes()
        digest=hashlib.sha1(
            b"blob "+str(len(raw)).encode("ascii")+b"\0"+raw
        ).hexdigest()
        if digest!=expected:
            raise DailySignalEvidenceHold("HOLD: original Daily model changed")
    return True


def model_observation(*, reader, indicator_fn, regime_fn, strategy_fn,
                      profile_fn, clock=time.time,
                      source_check=verify_readonly_daily_model_sources):
    """Pure orchestration of the original model, with injected offline fixtures.

    Strategy is configured EXACTLY as legacy compute_all_signals for SOL-USD:
    aggressive=True and the mid-cap profile. No alternative/new trade rules.
    """
    try:
        if source_check() is not True:
            raise DailySignalEvidenceHold("HOLD: Daily source fingerprint unverified")
        now=clock()
        if type(now) not in (int,float) or not math.isfinite(now):
            raise DailySignalEvidenceHold("HOLD: unknown UTC observation time")
        observed_at_s=int(now)
        today_utc=datetime.fromtimestamp(now,timezone.utc).date()
        expected_bar=today_utc-timedelta(days=1)
        data=reader(tickers=[TICKER])
        if type(data) is not dict or set(data)!={TICKER}:
            raise DailySignalEvidenceHold("HOLD: no single verified SOL data source")
        raw=data[TICKER]
        if (raw is None or raw.empty or len(raw)<MIN_HISTORY_DAYS
                or len(raw.index)!=len(raw)
                or not raw.index.is_unique
                or not raw.index.is_monotonic_increasing):
            raise DailySignalEvidenceHold("HOLD: missing/gapped Daily SOL history")
        latest=raw.index[-1]
        previous=raw.index[-2]
        if not hasattr(latest,"date") or not hasattr(previous,"date") \
                or latest.date()!=expected_bar \
                or previous.date()!=expected_bar-timedelta(days=1):
            raise DailySignalEvidenceHold(
                "HOLD: previous UTC daily SOL bar not complete or missing"
            )
        # The Yahoo daily candle dates are calendar labels. Reject any
        # intraday-looking timestamps, rather than treating an open candle
        # as closed and using it to select a direction.
        if (getattr(latest,"hour",1)!=0 or getattr(latest,"minute",1)!=0
                or getattr(latest,"second",1)!=0):
            raise DailySignalEvidenceHold("HOLD: market bars not at daily boundary")
        candle_open=datetime.combine(expected_bar,datetime.min.time(),
                                     tzinfo=timezone.utc)
        bar_started_at_s=int(candle_open.timestamp())
        profile=profile_fn(TICKER)
        if (type(profile) is not dict or profile.get("allow_short") is not False
                or profile.get("max_bull_leverage")!=1.5
                or profile.get("atr_mult")!=4.0):
            raise DailySignalEvidenceHold("HOLD: SOL original no-short profile changed")
        frame=indicator_fn(raw)
        regimes,bull_probs,bear_probs=regime_fn(frame)
        if (len(regimes)!=len(frame) or len(bull_probs)!=len(frame)
                or len(bear_probs)!=len(frame)):
            raise DailySignalEvidenceHold("HOLD: missing original Daily HMM history")
        strategy=strategy_fn(
            frame,regimes,bull_probs=bull_probs,bear_probs=bear_probs,
            aggressive=True,bull_leverage=profile["max_bull_leverage"],
            allow_short=profile["allow_short"],atr_mult=profile["atr_mult"]
        )
        last=int(strategy["Signal"].iloc[-1])
        prior=int(strategy["Signal"].iloc[-2])
        regime=str(regimes.iloc[-1])
        legacy_leverage=float(strategy["Leverage"].iloc[-1])
        if (last not in (-1,0,1) or prior not in (-1,0,1)
                or regime not in ("Bull","Bear","Chop")
                or not math.isfinite(legacy_leverage) or legacy_leverage<0):
            raise DailySignalEvidenceHold("HOLD: model output malformed")
        action=classify_signal(last,prior,regime)
        # Exact source adapter verifies the bounded time, completed candle,
        # original code blob, and fresh entry. It does NOT grant permission.
        fresh_buy=False
        if action=="buy":
            candidate=review_daily_signal(
                ticker=TICKER,last_signal=last,prior_signal=prior,
                regime=regime,action=action,
                bar_started_at_s=bar_started_at_s,
                observed_at_s=observed_at_s,now_s=observed_at_s,
                legacy_leverage=max(legacy_leverage,1.0)
            )
            if candidate.may_submit or candidate.trial_leverage!=1:
                raise DailySignalEvidenceHold("HOLD: signal adapter grants trade")
            fresh_buy=True
        elif action=="enter_short" or last==-1:
            raise DailySignalEvidenceHold("HOLD: SOL short forbidden by original model")
        return DailySolObservation(
            ticker=TICKER,daily_bar_utc=expected_bar.isoformat(),
            regime=regime,last_signal=last,prior_signal=prior,
            action=action,legacy_leverage=str(legacy_leverage),
            is_new_daily_sol_buy=fresh_buy,
            status=("NEW_SOL_BUY_REVIEW_ONLY_HOLD" if fresh_buy
                    else "NO_NEW_SOL_DAILY_ENTRY_HOLD")
        )
    except (DailySignalEvidenceHold,SignalReviewHold,ValueError,TypeError,
            AttributeError,KeyError,IndexError,OverflowError,OSError) as exc:
        raise DailySignalEvidenceHold(
            "HOLD: unable to establish a genuine completed Daily SOL signal"
        ) from exc


def run_readonly_model():
    verify_readonly_daily_model_sources()
    # Imports are deferred so CI can assert the code does not invoke any
    # exchange signing or legacy executable workflows.
    from data_loader import fetch_data
    from indicators import compute_all
    from hmm_engine import causal_hmm_regimes
    from strategy import generate_signals
    from backtester import get_asset_profile
    return model_observation(
        reader=fetch_data,indicator_fn=compute_all,
        regime_fn=causal_hmm_regimes,strategy_fn=generate_signals,
        profile_fn=get_asset_profile
    )


def main(argv=None):
    parser=argparse.ArgumentParser(
        description="Read-only original SOL Daily model. NEVER sends orders"
    )
    parser.add_argument("--read-only-signal",action="store_true")
    args=parser.parse_args(argv)
    if not args.read_only_signal:
        print("HOLD: only explicit read-only signal permitted",file=sys.stderr)
        return 2
    try:
        out=run_readonly_model()
    except (DailySignalEvidenceHold,ImportError) as exc:
        print("HOLD: original Daily SOL model unavailable: "+type(exc).__name__,
              file=sys.stderr)
        return 2
    print(json.dumps(asdict(out),sort_keys=True))
    print("HOLD: signal evidence only, no trading permission, no trade placed")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
