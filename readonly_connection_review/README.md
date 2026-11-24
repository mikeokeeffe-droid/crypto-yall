# Separate Hyperliquid Testnet public account checker — draft review

**STAGING ONLY. NOT DEPLOYED. NOT APPROVED FOR SERVER EXECUTION. NO TRADING.**

This standalone checker is intentionally separate from PR #41's network-disabled collector,
the existing heartbeat command, and all three existing bots. It is not a replacement
for PR #41's independently reviewed application-aware network gateway.

## Scope

- Fixed host: `api.hyperliquid-testnet.xyz`, HTTPS port 443, TLS certificate and hostname validation.
- Fixed path: `POST /info`.
- Fixed public Testnet account: `0xF14348Bdf59BA186F9CdD0fC5F369e1f6D3b7dC0`.
- Two fixed read-only query kinds only: `clearinghouseState` and `openOrders`.
- Timeout 8 seconds per request; maximum 512 KiB per response.
- No arbitrary URL, account, request type, redirects, proxy environment support, authentication or retries.
- No `/exchange`, wallet, seed phrase, private key, trade signing, database write or order handling.
- Prints only positions and open-order counts, not raw API data.
- No automatic start, service installation, workflow dispatch or schedule.

**Do not run the script on Hetzner yet.** Source-level restrictions alone are not host-level
isolation. Although direct `curl` from the interactive Hetzner login previously reached
Testnet, the protected PR #41 collector service remains explicitly network-blocked.

## Required before any Hetzner one-shot

1. Independent security reviewer to review this exact commit and check that it does not
   inherit wallet/API keys, bot secrets, privileged sockets or production DB access.
2. Confirm a separately reviewed **one-shot** run context, not the collector's
   protected service and not a trading executor. Maintain `testnet-collector-offline-review.service`
   inactive and `RefuseManualStart=yes`.
3. Independently validate outbound TLS/DNS/proxy boundary and no `/exchange` capability.
   The checker itself does NOT enforce process-level egress restrictions.
   Do not weaken existing firewall/systemd controls.
4. Confirm account address, two permitted queries and sanitized output.
   Obtain explicit operator approval scoped to exact reviewed artifact and execution path.
5. Log manual stop/rollback procedure and leave existing trading workflows unchanged.

The GitHub workflow on this branch runs only mocked offline tests. It cannot
connect to Testnet, activate any daemon or place an order.

**Status: Draft; HOLD for execution.**
