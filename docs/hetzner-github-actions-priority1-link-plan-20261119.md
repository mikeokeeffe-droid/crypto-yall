# Priority 1 — Hetzner ↔ original GitHub Actions: real link plan
19 November 2026 · PR #42 · review-only, no deployment or trading approval

## Verified, with scope
- Hetzner host shown by the operator: `ubuntu-4gb-hel1-1`, Ubuntu, existing `/opt/crypto-yall` offline review files; that folder is not a Git working tree. The separate `~/crypto-yall-monitor/repo` clone checked out draft PR #42 at `8073accc` and later pulled `fbab3d07`.
- Operator ran **7 heartbeat protocol tests and 3 localhost TCP tests** successfully on Hetzner. These are **one-host tests**, not two-server connectivity proof. The test-only heartbeat uses a hard-coded synthetic key; never deploy that key.
- Hetzner outbound `curl -I https://api.github.com` returned HTTP/2 200. The operator ran `python3 -m sender_review.github_actions_readonly_observer` and observed real, public GitHub Actions metadata for Daily, Intraday and Aggressive. This proves **Hetzner → GitHub API read access**, not persistent heartbeat, inbound reachability or order execution.
- The original workflows on `main` — `execute-trades.yml`, `execute-intraday.yml`, `execute-aggressive.yml` — each use `workflow_dispatch` and `ubuntu-latest`. They are not permanently running servers, and there is no `schedule` trigger in these exact workflows. A cancelled run does not by itself prove an outage; who dispatches them and their expected cadence must be determined before any missed-run alert is enabled.
- Latest draft branch offline CI checks pass; no real link is installed. Do not describe public run metadata as server heartbeats.

## Minimum viable connection topology

```
 GitHub-hosted short-lived trading jobs             Hetzner (continuous monitor)
              |                                              |
              |--- authenticated, brief run-session signal -->|   PROPOSED ONLY
              |<-- scoped receipt / status only -------------|
              |                                              |
              +--- existing bot execution (unchanged)        |
                                     ^                        |
                                     | Hetzner polls GitHub Actions
                                     +----- public run status -+
```

GitHub Actions cannot sustain a permanent host-to-host heartbeat between jobs. Separate:
1. **Run liveness:** Hetzner observes GitHub's last known run/update and compares with an **explicitly configured expected dispatch cadence**. If cadence is unknown, report `UNKNOWN_SCHEDULE`, not `HEALTHY` or `OUTAGE`. GitHub reporting is eventually consistent. Detect API errors/rate limits independently.
2. **Session heartbeat:** During *an actually running job*, a separately approved minimal, authenticated connection to Hetzner sends signed challenge/ACK frames with expiry, unique nonces, sequence and per-run identity. There is **no trade execution endpoint**. Job exit ends the session; an idle job is not a heartbeat failure.
3. **Hetzner service liveness:** A separate local watchdog checks the continuously running monitor, last successful API poll and observed active sessions; report degraded/outage distinctly. Merely receiving a valid signature proves the link peer only if the signing credential was independently provisioned and bound to the expected workload and channel.
4. **Alerts:** Notify on (a) missing *expected* dispatch, (b) active session losing ACK beyond policy, (c) monitor/service offline, (d) GitHub API stale/unreachable, or (e) authentication/replay attack. Alerts must be demonstrated on a real recipient before considered working; protect against alert floods.
5. **Orders remain independent:** link heartbeat can never authorize an order, cancel, close, re-entry, change leverage or override bot protections. Outage must not suspend independently configured exchange protections or leave a position unprotected; new monitor-driven entries stay disabled.

## Safest next authorized milestones

1. **Operator inventory (read-only, no secrets):** verify who dispatches the original jobs and expected frequency. Identify whether there is an existing SSH, HTTPS reverse-proxy or dedicated tunnel **already authorized**. Inspect Hetzner's *effective* firewall/provider ACL (UFW alone does not tell the whole story). Do not paste environment variables, keys or tokens.
2. **Choose and review transport:** preferably narrowly scoped, outbound-established identity-verified TLS/tunnel transport. If inbound HTTPS is necessary, review TLS certificate, fixed request body, endpoint authorization, public network exposure and denial/rate limits **before** opening a new port. Do not put a bearer key in a URL, GH issue, repo or workflow log. Avoid SSH command execution as a trading control channel.
3. **One synthetic cross-system proof:** from an **isolated, manually approved, non-trading GitHub job** to a deliberately enabled Hetzner heartbeat-only listener, confirm signed challenge/ACK, a real monotonic RTT measurement, secure redacted evidence and no route to any trading operation. Do not deploy or start such a listener under this PR without a separate operator-approved host/service/network change and rollback plan. Never repurpose the offline collector's locked-down systemd unit.
4. **Failure drill:** repeated messages, expired identity, wrong peer, disconnect/restart and delayed ACK all fail closed. Count lost heartbeats and verify real notification receipt. Use different test credentials from any live trading keys.
5. **Sign-off:** independently review actual host restrictions and authorization boundaries. Only then consider integrating an authenticated monitor-to-existing-executor handoff, with separately reviewed account-wide order ownership and protection. Live trading remains NO-GO.

## Explicit constraints
No Supabase integration. Do not change `main`, any existing live workflow, signing key, trading account, positions, older server, existing offline collector service or host firewall as part of this review. No testing against Hyperliquid endpoints. No trading authority. Keep PR #42 draft.

## Actual release evidence required
- [x] Offline protocol and local TCP heartbeat tests passed on Hetzner (operator screenshots, 19 Nov)
- [x] Hetzner read-only reachability to GitHub API and public run metadata
- [ ] Confirm real dispatch mechanism and expected cadence
- [ ] Confirm approved inbound/outbound transport and effective Hetzner edge policy
- [ ] Establish real two-endpoint authenticated heartbeat under separate authorization
- [ ] Measure RTT, jitter and disconnect/recovery on distinct systems
- [ ] Prove phone alert delivery for a failed active heartbeat
- [ ] Confirm trades/protective stops remain independently safe on a lost link
