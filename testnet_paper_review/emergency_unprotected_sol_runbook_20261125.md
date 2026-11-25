# One-shot SOL Testnet emergency exposure response — operator runbook

**Status: REVIEW ONLY. NOT DEPLOYED. No order or cancel authority.** This
runbook applies only to the pinned owner TESTNET account and the one-shot
$20 SOL, 1x isolated experiment. It does not authorize live trading.

## If the protective stop is missing or ambiguous after a fill

1. Treat the position as **UNPROTECTED** immediately. Freeze all new entry
   attempts and leave the original one-shot journal permanently consumed.
   Never retry the original grouped order after a timeout.
2. Inspect the pinned **Testnet** account on the official Testnet interface
   and get fresh independent `clearinghouseState`, `openOrders`, and
   `frontendOpenOrders` evidence. Do not mistake a successful API ACK for
   a verified live stop.
3. If there is any unexpected/foreign position or unrelated order, **do not
   use an automated rescue tool**. Escalate to the human account owner.
   A matching SOL position alone is not sufficient ownership evidence.
4. With explicit operator approval on the **Testnet interface**, close any
   unprotected SOL exposure **using reduce-only**, checking that no additional
   SOL exposure can be opened. If a close order times out or returns an
   unknown acknowledgement, **do not blind-retry**. Recheck positions and
   order status first, and escalate until resolved.
5. Do not cancel any remaining take-profit/stop order until the account is
   independently confirmed flat, or the operator has reviewed the precise
   exposure and exchange state. Cancel verified orphaned protective orders
   only after flat confirmation.
6. Repeat independent Testnet account reads to confirm **zero positions and
   zero open orders**. Record actual evidence, error/recovery steps and order
   IDs privately, without signing keys. Leave the Testnet sender OFF until
   separately reviewed and reauthorized.

The `testnet_emergency_close_review.py` module only produces an unsigned,
bounded IOC **reduce-only review proposal**, and returns `may_send=False`.
It never places a trade. A 3% IOC limit bound is **not** a guaranteed fill or
maximum loss. A missing stop or missing network access creates a human
intervention requirement, not an automatic permission to close arbitrary
positions. No current release provides an independently reviewed automated
emergency exit service.
