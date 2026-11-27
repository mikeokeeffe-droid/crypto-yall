# Read-only watchdog service review — HOLD

These units are draft deployment assets, not an instruction to install or enable
them. The original bots and both Testnet senders must remain unchanged and held.

The timer requests a check every 15 seconds. The oneshot is limited to 12 seconds
plus a two-second stop timeout. A timer does not guarantee successful or timely
sampling; it cannot detect its own failure or a whole-host outage.

Before installation: verify testadmin user/group, root-owned non-writable
reviewed code under /opt/crypto-yall/testnet_watchdog, and the exact code digest.
Inventory the bind-mounted trading evidence directory without displaying file
contents; confirm it contains no signing secrets and can be mounted read-only.
The separate watchdog directory must be owned by testadmin, mode 0700, and
its ledger explicitly initialized once, mode 0600. Never recreate a lost ledger.
Check the service sandbox and actual SQLite read-only access on the host.

The service needs DNS and HTTPS for the pinned Testnet read-only client.
The unit is NOT a network egress allowlist: host-level destination isolation
and independent identity separation still need review. The same UID is used
only because the existing journal validators require their owner. It is not
proof of separation from a future signer. Do not pass keys or Telegram secrets
to this service. No OnFailure transport is configured here.

Before trading approval: independently verify missed-cycle/dead-host alerting,
authenticated server-side incident delivery, emergency exit, exclusive runner,
and separate release approval. A healthy flat cycle is never trading authority.
