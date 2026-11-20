# Standalone heartbeat review — mandatory environment gate (NOT ready to run)

This change applies **only** to PR #43 and its one-shot no-trading GitHub SSH heartbeat. It does not change the original Daily, Intraday or Aggressive workflows, wallets, servers or exchange permissions.

## Configure before approving merge or running anything

1. In GitHub, open **Repository Settings → Environments** and create environment **`hetzner-heartbeat-review`**. Require a reviewer who is independent from the code author and disallow self-approval when the setting is offered. Restrict deployments to **selected branch: `main`**. Inspect these controls after saving and before any workflow dispatch. Do not weaken repository or organization policy.
2. Add **environment secrets**, NOT repository secrets:
   - `HETZNER_HEARTBEAT_REVIEW_ENV_PRIVATE_KEY`: the full dedicated Termius `crypto-yall-heartbeat` OpenSSH **private** key, including BEGIN and END lines. Never paste it in a PR, comment or chat.
   - `HETZNER_HEARTBEAT_REVIEW_ENV_HOST_KEY_ED25519`: the independent, pre-verified Hetzner **public server host key** line starting `ssh-ed25519 `; preserve the space and entire blob.
3. Before adding the private key, confirm this SSH identity is a **dedicated, non-trading heartbeat identity** only. The public host key must match the server fingerprint verified from a trusted server session, not an unauthenticated `ssh-keyscan` result.
4. The previous repository-level secrets `HETZNER_HEARTBEAT_SSH_KEY` and `HETZNER_HEARTBEAT_HOST_KEY_ED25519` are **not used by PR #43**. After the protected environment is verified, consider removing those old secrets only after checking that no other workflow depends on them. Keeping identical names in repository scope would provide a less robust fallback; this PR deliberately uses distinct names instead.
5. An independent security reviewer must review the actual PR diff and remaining server isolation questions. Claude's automated review can find problems but is not an independent human approval.
6. Only after the above, obtain **separate explicit approvals** for merging and for a one-shot manual workflow dispatch on `main`. The manual confirm phrase is `RUN_READONLY_HEARTBEAT`. Do not dispatch on unreviewed code.

## Known open security items

- Code and passing CI **cannot prove** GitHub environment protection rules were configured correctly. A workflow-level `if: github.ref == 'refs/heads/main'` is not a permissions barrier.
- Confirm on-host `cryptoheartbeat` has **no sudo**, privileged groups (including `docker`), writeable startup scripts, trading credentials, or read access to exchange/account secrets. Review the forced command, account shell, root ownership, authorized key count, SSH effective settings, firewall and server access logs; use redacted, read-only evidence.
- Confirm independent authentication/approval protection for repository changes and the default branch (branch protection/rulesets where available).
- The SSH subprocess now uses a bounded read: stdout is capped to 501 bytes for overflow detection and stderr is discarded. A deadline and forced process termination apply; the probe timeout is 20 seconds and the job timeout is 2 minutes. Independent review should verify the read/cleanup logic.
- GitHub-hosted runner IP ranges can change frequently. **Do not blindly restrict port 22 to a narrow IP list**: this could lock out the operator and break connectivity. Any firewall changes require an independently reviewed plan and recovery-console access.
- A passing mocked CI check is **not** a successful real GitHub-to-Hetzner connection, nor proof of absence of trading authority. No real workflow has been dispatched.

## What tests prove

Offline unit tests cover the SSH probe, host-key parsing, nonce/freshness ACK, hostile responses, options to disable forwarding/proxying, initial `0600` file creation, bounded local subprocess output, timeout/overflow behavior and the workflow's required environment reference and distinct secret names. All external SSH attempts are mocked in CI.

**Status:** REVIEW ONLY; not merged, deployed or authorized to run.
