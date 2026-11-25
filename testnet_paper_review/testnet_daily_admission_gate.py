"""TESTNET Daily admission rules: pure, offline, no order or signing capability.

Accepts snapshots that a separately reviewed, read-only Testnet information
client might collect. This module NEVER sends a network request or any order.
A READY_FOR_REVIEW outcome is NOT order placement authorization.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from collections.abc import Mapping

EXPECTED_ACCOUNT = "0xF14348Bdf59BA186F9CdD0fC5F369e1f6D3b7dC0"
EXPECTED_NETWORK = "hyperliquid-testnet"
ALLOWED_COIN = "SOL"
MIN_NOTIONAL = Decimal("12")
MAX_NOTIONAL = Decimal("25")
MAX_AGE_SECONDS = 15


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str

    @property
    def allows_order(self):
        # This module's results NEVER grant permission to place an order.
        return False


def hold(reason: str) -> Decision:
    return Decision("HOLD", reason)


def _amount(raw):
    if type(raw) is not str or not re.fullmatch(r"(?:0|[1-9]\d*)(?:\.\d{1,8})?", raw):
        return None
    try:
        result = Decimal(raw)
        if result.is_finite():
            return result
    except InvalidOperation:
        pass
    return None


def assess(*, account, network, state, open_orders, signal,
           now_s, snapshot_at_s, notional_usdc="20", leverage=1,
           account_mode=None, spot_state=None) -> Decision:
    """Evaluate explicit public account snapshot + one Daily signal; HOLD by default.

    No trusted orders, prices or identities may be supplied by unreviewed callers.
    A real execution path also needs independent signer, account/query provenance,
    durable ownership, reconciliation, exact code-approval, and protective exits.
    """
    if network != EXPECTED_NETWORK:
        return hold("Unknown network or Mainnet: Testnet is mandatory")
    if type(account) is not str or account.lower() != EXPECTED_ACCOUNT.lower():
        return hold("Wrong Testnet account identity")
    if any(type(x) is not int for x in (now_s, snapshot_at_s)):
        return hold("Invalid snapshot timestamps")
    if not 0 <= now_s - snapshot_at_s <= MAX_AGE_SECONDS:
        return hold("Stale/future account snapshot")
    if type(state) is not dict or type(open_orders) is not list:
        return hold("Missing/invalid independent Testnet state")
    # A single open position or order anywhere on the account is an absolute
    # stop. This includes manual positions, stop-losses, take-profits and
    # positions managed by another bot. Do not 'adopt' the user's manual SOL.
    positions = state.get("assetPositions")
    if type(positions) is not list:
        return hold("Unknown open position state")
    if positions:
        return hold("Account has an existing manual/bot position: no new entry")
    if open_orders:
        return hold("Account has outstanding orders: no new entry")
    margin = state.get("marginSummary")
    if type(margin) is not dict:
        return hold("Unverified perp collateral summary")
    # Unified Account reports collateral and holds in spotClearinghouseState.
    # Do not require a positive perp clearinghouseState.accountValue in this
    # mode: the independently observed perp view may legitimately show zero.
    # A stale UI balance is not evidence; the caller MUST use the pinned public
    # TESTNET spot /info response and public userAbstraction mode, with a
    # second matching snapshot before any human review.
    perp_available = _amount(state.get("withdrawable"))
    perp_equity = _amount(margin.get("accountValue"))
    if perp_available is None or perp_equity is None:
        return hold("Invalid or missing perpetual account summary")
    requested = _amount(notional_usdc)
    if requested is None or not MIN_NOTIONAL <= requested <= MAX_NOTIONAL:
        return hold("Order outside $12-$25 Testnet review bounds")
    if account_mode == "unifiedAccount":
        if type(spot_state) is not dict or type(spot_state.get("balances")) is not list:
            return hold("Missing independently observed Unified Testnet Spot USDC")
        balances = spot_state["balances"]
        if len(balances) > 1000 or any(type(row) is not dict for row in balances):
            return hold("Malformed Unified Spot balance view")
        usdc = [row for row in balances if row.get("coin") == "USDC"]
        if len(usdc) != 1:
            return hold("Missing or duplicate Unified USDC collateral")
        total = _amount(usdc[0].get("total"))
        held = _amount(usdc[0].get("hold"))
        if total is None or held is None or held > total:
            return hold("Invalid or overheld Unified USDC collateral")
        if total - held < requested:
            return hold("Insufficient independent Unified USDC collateral")
    elif account_mode in (None, "disabled"):
        if spot_state is not None:
            return hold("Unexpected Spot collateral on Standard perp review")
        if perp_available < requested or perp_equity < requested:
            return hold("Insufficient independently confirmed perp collateral")
    else:
        # Portfolio Margin and other modes require their own verified
        # margin/risk calculation, not this single-USDC review.
        return hold("Unsupported or unknown Testnet account mode")
    if type(leverage) is not int or leverage != 1:
        return hold("Leverage must equal exactly 1x")
    if type(signal) is not dict:
        return hold("Missing Daily signal")
    if signal.get("coin") != ALLOWED_COIN:
        return hold("Only SOL is within trial scope")
    if signal.get("action") not in ("buy", "enter_short"):
        return hold("No fresh Daily entry signal")
    if signal.get("mode") != "OFFLINE_SIGNAL_REVIEW":
        return hold("Unreviewed signal source")
    if type(signal.get("observed_at_s")) is not int or not 0 <= now_s - signal["observed_at_s"] <= MAX_AGE_SECONDS:
        return hold("Stale/future Daily signal")
    # Not an execution authorization; never return ACTIVE/ENABLED/EXECUTE.
    return Decision("READY_FOR_REVIEW", "No existing positions/orders in supplied Testnet fixture; independent approval still required")
