# SOL Testnet isolated-host predeployment check

**Status: READ-ONLY / NO-GO.** This is a preparation checklist, not a
deployment authorization, secret-install procedure or service activation.

## Existing GitHub verification

- The private API key was already verified using GitHub's protected
  `crypto-yall-testnet` environment in the successful read-only
  [verification run](https://github.com/mikeokeeffe-droid/crypto-yall/actions/runs/45561480906).
  Do **not** repeat the key setup, copy it into chat or transfer it to the
  Testnet server before an explicit and separate deployment review.
- PR #46 only contains draft, blocked sender code. The original trading
  workflows remain unchanged. The dedicated server's prior
  `testnet-collector-offline-review.service` must remain inactive.

## Read-only host preparation

On a trusted copy of the reviewed PR #46 branch, from the repository root,
without configuring any credentials, the operator can run:

```sh
python3 -B -m testnet_paper_review.testnet_server_deployment_check --read-only-check
```

It uses public Testnet `/info` only and prints a public, diagnostic receipt.
It checks Unified Account mode, available mock USDC, no positions/orders, one
named publicly associated API agent and public SOL metadata. It does **not**
place/cancel/close orders, read signing keys, install services, initialize
the permanent journal or configure network access.

For a read-only service-state inspection (no `start`, `restart`, `enable`
or `daemon-reload`):

```sh
systemctl is-active testnet-collector-offline-review.service
systemctl show testnet-collector-offline-review.service -p ActiveState -p SubState -p ExecStart --no-pager
```

These commands read state only. They do not establish that the isolated
**sender** is deployed: it isn't. Neither a good service diagnostic nor the
public account receipt authorizes live Testnet execution.

## Release gates still required

- Independent review of the full sender + emergency close path, including
  unknown-ACK recovery and safe handling if stops vanish.
- Explicit dedicated server choice, persistent journal setup, isolation
  and outbound TESTNET-only host restrictions.
- Verified safe handling of the already configured, protected Testnet
  signing key, without logging or exporting it to this repository.
- Live trading-capable margin and 1x isolated leverage verified on the
  real account; the public Unified Spot balance alone is insufficient.
- Explicit approval of the exact trial order before any Testnet submission.

**Do not** merge the PR or change `ACTIVATION_HOLD=True` as part of
this check. Never run the original Mainnet-capable executors for this trial.


## Local host inventory (separate from GitHub checks)

On the **actual dedicated Ubuntu host** only, from the checked-out review
branch's repository root, this command inspects the pre-existing collector
and the possible one-shot sender unit via **read-only** systemd properties:

```sh
python3 -B -m testnet_paper_review.testnet_local_host_inventory --read-only-check
```

It prints only a boolean summary. It never starts or installs anything,
does not use sudo, reads no environment values, and refuses a running
collector or sender. The sender unit being **not installed** is expected
at this stage. GitHub CI tests use a fake systemd reader, **not this server**.
This targeted unit inspection is **not** a host-wide process audit and
must not be interpreted as evidence that all other services are inactive.

If the command reports HOLD, leave services untouched and inspect the
error; do **not** relax the service checks or enable trading to make it green.
