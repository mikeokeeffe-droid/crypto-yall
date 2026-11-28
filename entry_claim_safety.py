"""Conservative per-bot entry-claim helpers for the offline integration draft.

A Gist claim is NOT an atomic cross-bot reservation. No claimed entry is
automatically cleared merely because the latest position snapshot is flat.
Only a local pre-submit skip proves there was no exchange submission. An
unknown, error, timeout or raised exception must remain unresolved until
order-aware reconciliation (or an explicitly reviewed manual resolution).
"""

ENTRY_ACTIONS = frozenset(("open_long", "open_short", "pyramid_long", "pyramid_short"))


def blocks_entry_with_pending_claim(trade: dict, pending_claims: dict) -> bool:
    """Block opening or increasing a coin whose own claim is still unresolved.

    Protective closes are always outside this entry-only gate.
    """
    return (
        trade.get("action") in ENTRY_ACTIONS
        and trade.get("hl_coin") in (pending_claims or {})
    )


def safe_to_release_pre_submit_skip(result: dict) -> bool:
    """Only the current executors' local size/minimum checks emit 'skipped'.

    The exchange response parser emits filled/error/unknown, never skipped.
    If that contract changes, this function and offline order-path tests must
    be reviewed together; it is NOT proof of a durable shared reservation.
    """
    return result.get("status") == "skipped"
