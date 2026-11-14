"""CI-only audit of ALL original executors' explicit Info read dependencies.

The five supported synthetic Info reads are NOT the entire interface:
Daily's user_fills and user_funding_history must remain unavailable until
a separately authenticated read-only evidence source is reviewed. Green
compatibility tests MUST NOT imply that actual live bots can be cut over.

No executor import, SDK, secrets, database, network or trading authority.
This source-only inventory does not prove transitive HTTP/candle dependencies,
full runtime call-graph coverage or authentic exchange provenance.
"""
import ast
from dataclasses import dataclass
from pathlib import Path

FILES = (
    "hyperliquid_executor.py",
    "intraday_executor.py",
    "aggressive_executor.py",
)
CORE_READS = frozenset((
    "user_state", "spot_user_state", "all_mids", "meta",
))
HISTORY_READS = frozenset(("user_fills", "user_funding_history"))
REQUIRED_READS = CORE_READS | HISTORY_READS
# In Intraday/Aggressive, 'info' is ALSO a strategy signal dictionary.
# Existing single 'info.get' on each is NOT a Hyperliquid Info method.
SIGNAL_GET_COUNTS = {
    "hyperliquid_executor.py": 0,
    "intraday_executor.py": 1,
    "aggressive_executor.py": 1,
}


@dataclass(frozen=True)
class OriginalInfoReadInventory:
    state: str = "hold"
    reason: str = "source review not complete"
    source_shape_matches: bool = False
    methods: tuple[str, ...] = ()
    unsupported_history_reads: tuple[str, ...] = ()
    signer_free_runtime_verified: bool = False
    account_history_complete: bool = False
    trading_authorized: bool = False


def audit_original_info_read_surface_offline(sources, *, history_adapter=None):
    """Return HOLD irrespective of fixture data or claimed history adapter.

    The optional argument is intentionally never used to establish coverage:
    this static review cannot authenticate an external implementation.
    """
    held = OriginalInfoReadInventory()
    if (type(sources) is not dict or set(sources) != set(FILES)
            or history_adapter is not None):
        return held
    used = set()
    for filename in FILES:
        source = sources[filename]
        if type(source) is not str or not 0 < len(source) <= 500_000:
            return held
        try:
            tree = ast.parse(source, filename=filename)
        except (SyntaxError, ValueError, TypeError):
            return held
        signal_gets = 0
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "info"):
                continue
            method = node.func.attr
            if method == "get":
                signal_gets += 1
                continue
            if method not in REQUIRED_READS:
                return OriginalInfoReadInventory(
                    reason="unreviewed original Info method: " + method,
                )
            used.add(method)
        if signal_gets != SIGNAL_GET_COUNTS[filename]:
            return OriginalInfoReadInventory(
                reason="signal Info dictionary shadowing changed",
            )
    if used != REQUIRED_READS:
        return OriginalInfoReadInventory(
            reason="original Info read dependency set changed; re-audit",
            methods=tuple(sorted(used)),
        )
    return OriginalInfoReadInventory(
        reason="five synthetic core-read helpers are exercised, but order "
               "fills and funding history remain unauthenticated and blocked",
        source_shape_matches=True,
        methods=tuple(sorted(used)),
        unsupported_history_reads=tuple(sorted(HISTORY_READS)),
    )
