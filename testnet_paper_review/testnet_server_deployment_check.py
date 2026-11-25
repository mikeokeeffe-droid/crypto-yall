"""Credential-free Testnet server predeployment inspection.

Safe to run on an isolated host with --read-only-check. ALL network calls
are public POST /info to the pinned Hyperliquid Testnet host. No keys,
GitHub Secrets, Order/Exchange client, /exchange, systemctl commands,
journal initialization, file writes or system service activation.

Success means public observations are consistent; NEVER trade authorization.
Agent association is checked publicly, but no private signing capability is
checked or accessed here. Designed for a human-reviewed server handoff.
"""
import argparse
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import json
import sys
import time

from testnet_paper_review.testnet_daily_readonly_preflight import (
    review_once, ReadOnlyError
)
from testnet_paper_review.testnet_spot_funds_probe import (
    read_account_mode, fetch_spot, review_usdc_spot, SpotHold
)
from testnet_paper_review.testnet_public_agent_review import (
    review_public_agents, AgentHold
)
from testnet_paper_review.testnet_public_sol_market import (
    read_sol_market_once, MarketReadHold
)
from testnet_paper_review.testnet_daily_admission_gate import EXPECTED_ACCOUNT

MAX_SPAN_S=18
MIN_USDC=Decimal("20")


class HostPredeployHold(RuntimeError):
    pass


@dataclass(frozen=True)
class HostReadOnlyReceipt:
    owner: str
    mode: str
    spot_usdc_available: str
    positions: int
    open_orders: int
    testnet_named_owner_agents: int
    sol_mid: str
    sol_size_decimals: int
    status: str = "PUBLIC_TESTNET_PREDEPLOY_REVIEW_ONLY_HOLD"

    @property
    def may_send(self):
        return False

    @property
    def verifies_private_signer(self):
        return False


def inspect_server_public_testnet(*, account_reader=review_once,
                                   mode_reader=read_account_mode,
                                   spot_reader=fetch_spot,
                                   agent_reader=review_public_agents,
                                   market_reader=read_sol_market_once,
                                   clock=None):
    """Bounded public-only diagnostics. Never treats Spot as live order approval."""
    if clock is None:
        clock = lambda: int(time.time())
    try:
        began=clock()
        a=account_reader()
        mode=mode_reader()
        spot=review_usdc_spot(spot_reader())
        agents=agent_reader()
        market=market_reader()
        ended=clock()
        if (type(began) is not int or type(ended) is not int
                or not 0 <= ended-began <= MAX_SPAN_S):
            raise HostPredeployHold("HOLD: stale public Testnet server evidence")
        if a["decision"].allows_order or a["decision"].status != "HOLD":
            raise HostPredeployHold("HOLD: public account check unexpectedly permits orders")
        if a["positions"] != 0 or a["open_orders"] != 0:
            raise HostPredeployHold("HOLD: user has existing position/open orders")
        if mode != "unifiedAccount":
            raise HostPredeployHold("HOLD: expected Unified Account mode missing")
        if spot["may_trade"] is not False:
            raise HostPredeployHold("HOLD: public Spot source unexpectedly grants trade")
        available=Decimal(spot["available"])
        if not available.is_finite() or available < MIN_USDC:
            raise HostPredeployHold("HOLD: Testnet Unified USDC below $20")
        if (agents["trading_authorized"] is not False
                or type(agents["active_named_owner_agents"]) is not int
                or agents["active_named_owner_agents"] != 1):
            raise HostPredeployHold("HOLD: no unique publicly verified Testnet owner agent")
        if market.symbol != "SOL" or market.allows_trading \
                or not 0 <= market.size_decimals <= 5:
            raise HostPredeployHold("HOLD: public SOL market not verified")
        return HostReadOnlyReceipt(
            owner=EXPECTED_ACCOUNT,mode=mode,
            spot_usdc_available=spot["available"],
            positions=0,open_orders=0,
            testnet_named_owner_agents=1,
            sol_mid=market.mid_price,
            sol_size_decimals=market.size_decimals
        )
    except (HostPredeployHold,ReadOnlyError,SpotHold,AgentHold,MarketReadHold,
            KeyError,TypeError,ValueError,InvalidOperation,TimeoutError,OSError) as exc:
        raise HostPredeployHold(
            "HOLD: public Testnet server predeployment evidence incomplete"
        ) from exc


def main(argv=None):
    parser=argparse.ArgumentParser(description="Public Testnet server preflight (no trading)")
    parser.add_argument("--read-only-check",action="store_true")
    args=parser.parse_args(argv)
    if not args.read_only_check:
        print("HOLD: explicit read-only check required",file=sys.stderr)
        return 2
    try:
        result=inspect_server_public_testnet()
    except HostPredeployHold:
        print("HOLD: public Testnet prerequisites not fully observed",file=sys.stderr)
        return 2
    print(json.dumps(asdict(result),sort_keys=True))
    print("HOLD: signer access, server exclusivity, journal location, "
          "emergency exit and independent review NOT verified")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
