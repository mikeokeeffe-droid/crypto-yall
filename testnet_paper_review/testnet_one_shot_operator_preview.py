"""Read-only operator preview of ONE $20 SOL TESTNET trial, both sides.

This is NOT the original Daily trading signal and cannot select a direction,
sign, send, close, cancel, claim a journal entry, initialize a new journal,
activate the sender, or update leverage. A quote is indicative, not a limit
order approval: all pricing must be recomputed immediately before any separately
approved actual trade.

On the dedicated Ubuntu host:
  .venv/bin/python -B -m testnet_paper_review.testnet_one_shot_operator_preview --read-only-preview
"""
import argparse
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_DOWN
import json
import sys

from testnet_paper_review.offline_daily_bracket_plan import _price
from testnet_paper_review.single_host_live_journal import (
    SingleHostOneShotJournal, PersistentHold
)
from testnet_paper_review.testnet_server_deployment_check import (
    inspect_server_public_testnet, HostPredeployHold
)
from testnet_paper_review.testnet_sdk_server_client_preflight import (
    inspect_sdk_client, load_local_agent, SignerSDKHold
)
from testnet_paper_review.offline_order_guard import (
    TESTNET_ACCOUNT, TESTNET_ENDPOINT
)

JOURNAL_PATH="/home/testadmin/crypto-yall-testnet-state/testnet-one-shot.sqlite3"
NOTIONAL=Decimal("20")
MAX_ENTRY_SLIPPAGE=Decimal("0.005")
TAKE_PROFIT=Decimal("0.02")
STOP_LOSS=Decimal("0.01")


class OneShotPreviewHold(RuntimeError):
    pass


@dataclass(frozen=True)
class SidePreview:
    direction: str
    coin: str
    indicative_entry_limit: str
    size_sol: str
    worst_case_entry_notional_usdc: str
    indicative_take_profit_trigger: str
    indicative_stop_loss_trigger: str
    reduce_only_exits_required: bool = True
    permissions: str = "NO_TRADING_AUTHORITY"


@dataclass(frozen=True)
class ReadOnlyTrialPreview:
    account: str
    endpoint: str
    agent: str
    current_testnet_mid: str
    spot_usdc_available: str
    position_count: int
    open_order_count: int
    journal_empty: bool
    long: SidePreview
    short: SidePreview
    requested_leverage: int = 1
    actual_leverage_verified: bool = False
    exchange_exits_verified: bool = False
    original_daily_signal_verified: bool = False
    may_send: bool = False
    status: str = "READ_ONLY_SOL_TESTNET_OPERATOR_PREVIEW_HOLD"


def preview_side(*, direction, mid, decimals):
    if direction not in ("long","short") or type(decimals) is not int \
            or not 0 <= decimals <= 5:
        raise OneShotPreviewHold("HOLD: invalid SOL preview direction/precision")
    if type(mid) is not Decimal or not mid.is_finite() \
            or not Decimal("1") <= mid <= Decimal("10000"):
        raise OneShotPreviewHold("HOLD: invalid TESTNET SOL reference quote")
    is_long=direction=="long"
    precision=6-decimals
    entry=Decimal(_price(
        mid*(1+MAX_ENTRY_SLIPPAGE if is_long else 1-MAX_ENTRY_SLIPPAGE),
        decimals=precision,round_up=is_long
    ))
    quantity=(NOTIONAL/entry).quantize(
        Decimal(1).scaleb(-decimals),rounding=ROUND_DOWN
    )
    effective=entry*quantity
    if not Decimal("12") <= effective <= NOTIONAL:
        raise OneShotPreviewHold("HOLD: $20 trial would violate SOL lot/notional rules")
    take=Decimal(_price(
        mid*(1+TAKE_PROFIT if is_long else 1-TAKE_PROFIT),
        decimals=precision,round_up=is_long
    ))
    stop=Decimal(_price(
        mid*(1-STOP_LOSS if is_long else 1+STOP_LOSS),
        decimals=precision,round_up=not is_long
    ))
    if not (stop < mid < take if is_long else take < mid < stop):
        raise OneShotPreviewHold("HOLD: invalid protective trigger orientation")
    return SidePreview(
        direction=direction,coin="SOL",
        indicative_entry_limit=format(entry,"f"),size_sol=format(quantity,"f"),
        worst_case_entry_notional_usdc=format(effective,"f"),
        indicative_take_profit_trigger=format(take,"f"),
        indicative_stop_loss_trigger=format(stop,"f"),
    )


def inspect_one_shot_preview(*, public_check=inspect_server_public_testnet,
                              wallet_loader=load_local_agent,
                              sdk_check=inspect_sdk_client,
                              journal_factory=SingleHostOneShotJournal):
    """Observe public TESTNET, verified owner SDK and existing on-host journal.

    All objects are read-only here: no wallet material in return values,
    no exchange signed actions, no journal claims, and no new files.
    The host must already have the private dedicated Testnet key and journal.
    """
    try:
        public=public_check()
        if (public.owner.lower()!=TESTNET_ACCOUNT.lower()
                or public.mode!="unifiedAccount"
                or type(public.positions) is not int or public.positions != 0
                or type(public.open_orders) is not int or public.open_orders != 0
                or type(public.sol_size_decimals) is not int):
            raise OneShotPreviewHold("HOLD: owner or open position/order not verified")
        if Decimal(public.spot_usdc_available)<NOTIONAL:
            raise OneShotPreviewHold("HOLD: insufficient Testnet USDC")
        sdk=sdk_check(wallet=wallet_loader())
        if (sdk.owner.lower()!=TESTNET_ACCOUNT.lower()
                or sdk.testnet_endpoint!=TESTNET_ENDPOINT
                or type(sdk.sol_asset_id) is not int
                or sdk.may_send is not False):
            raise OneShotPreviewHold("HOLD: incorrect TESTNET SDK owner/client")
        with journal_factory(JOURNAL_PATH) as j:
            state=j.view()
            if state != {"frozen":False,"claim":None}:
                raise OneShotPreviewHold("HOLD: one-shot journal has already been used")
        quote=Decimal(public.sol_mid)
        long=preview_side(direction="long",mid=quote,
                          decimals=public.sol_size_decimals)
        short=preview_side(direction="short",mid=quote,
                           decimals=public.sol_size_decimals)
        return ReadOnlyTrialPreview(
            account=TESTNET_ACCOUNT,endpoint=TESTNET_ENDPOINT,
            agent=sdk.agent,current_testnet_mid=str(quote),
            spot_usdc_available=public.spot_usdc_available,
            position_count=0,open_order_count=0,
            journal_empty=True,long=long,short=short
        )
    except (HostPredeployHold,SignerSDKHold,PersistentHold,
            OneShotPreviewHold,TypeError,KeyError,AttributeError,
            ValueError,ArithmeticError,OSError) as exc:
        raise OneShotPreviewHold(
            "HOLD: unable to preview verified one-shot SOL TESTNET trial"
        ) from exc


def main(argv=None):
    parser=argparse.ArgumentParser(description="Review-only SOL Testnet trial preview")
    parser.add_argument("--read-only-preview",action="store_true")
    args=parser.parse_args(argv)
    if not args.read_only_preview:
        print("HOLD: explicit --read-only-preview required",file=sys.stderr)
        return 2
    try:
        receipt=inspect_one_shot_preview()
    except OneShotPreviewHold as exc:
        print(str(exc),file=sys.stderr)
        return 2
    print(json.dumps(asdict(receipt),sort_keys=True,indent=2))
    print("HOLD: both directions are only price examples, NOT a Daily strategy signal.")
    print("HOLD: 1x isolated leverage, independent emergency exit, latest prices and "
          "specific human trade approval remain outstanding; no trade placed.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
