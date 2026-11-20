# PR #43 complete source bundle

This document contains the exact five changed files from commit `e7aba3687f3faab01fc75fd4d0f57f74664153db` for external read-only security review. Files are from public GitHub repository source only. No GitHub secrets or private SSH key values are included.

## File 1: `.github/workflows/manual-hetzner-ssh-heartbeat-review.yml`

Git blob: `312a105da798119db743089875b4ee61a9ce5f2d`

```yaml
# REVIEW-ONLY: manually dispatched after independent security review.
# PRECONDITION: explicitly configure the environment below with main-only
# deployment branch policy, independent required reviewer, and secrets stored
# ONLY at environment scope. Do not create matching repository-level secrets.
# Never merge or dispatch until environment protections have been inspected.
# This workflow is NOT available for workflow_dispatch until reviewed and
# present on the repository default branch. NEVER run on unreviewed PR code.
# No trading workflow, exchange client or signing credentials are used.
name: Manual Hetzner SSH Heartbeat Review (no trading)

on:
  workflow_dispatch:
    inputs:
      confirm:
        description: 'Type RUN_READONLY_HEARTBEAT to acknowledge this one-shot SSH test'
        required: true
        type: string

permissions:
  contents: read

concurrency:
  group: manual-hetzner-heartbeat-review
  cancel-in-progress: false

jobs:
  heartbeat-review:
    # No pull_request, push, schedule or callable workflow trigger.
    # Restrict deployment to reviewed default-branch code only.
    if: github.ref == 'refs/heads/main' && inputs.confirm == 'RUN_READONLY_HEARTBEAT'
    # The branch if-guard alone is NOT a secret boundary. Environment rules
    # must be configured by the repository administrator before promotion.
    environment: hetzner-heartbeat-review
    runs-on: ubuntu-latest
    timeout-minutes: 2
    steps:
      - name: Check out only reviewed default-branch code
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          persist-credentials: false
      - name: Verify isolated probe contract without network
        run: python3 -m unittest sender_review.test_github_to_hetzner_heartbeat_probe_review_only -v
      - name: One-shot verified SSH heartbeat (never trade)
        env:
          HETZNER_HEARTBEAT_SSH_KEY: ${{ secrets.HETZNER_HEARTBEAT_REVIEW_ENV_PRIVATE_KEY }}
          HETZNER_HEARTBEAT_HOST_KEY_ED25519: ${{ secrets.HETZNER_HEARTBEAT_REVIEW_ENV_HOST_KEY_ED25519 }}
        run: python3 -m sender_review.github_to_hetzner_heartbeat_probe_review_only

```

## File 2: `.github/workflows/review-isolated-hetzner-heartbeat.yml`

Git blob: `e90c247dd2afa846b85062419e82b46f2b9e69f2`

```yaml
name: Review Isolated Hetzner SSH Heartbeat (offline only)

on:
  pull_request:
    branches: [main]
    paths:
      - 'sender_review/github_to_hetzner_heartbeat_probe_review_only.py'
      - 'sender_review/test_github_to_hetzner_heartbeat_probe_review_only.py'
      - '.github/workflows/manual-hetzner-ssh-heartbeat-review.yml'
      - '.github/workflows/review-isolated-hetzner-heartbeat.yml'
  workflow_dispatch: {}

permissions:
  contents: read

jobs:
  offline-heartbeat-review:
    runs-on: ubuntu-latest
    timeout-minutes: 3
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - name: Verify heartbeat probe via mocks only — no SSH, no secrets
        run: python3 -m unittest sender_review.test_github_to_hetzner_heartbeat_probe_review_only -v

```

## File 3: `docs/hetzner-heartbeat-protected-environment-review-20261120.md`

Git blob: `eb05d651f76061526c7c59755c7544fb80ec8f2a`

```markdown
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
- The Python subprocess currently uses `capture_output=True`: ACK validation rejects more than 500 bytes **after capture**, but memory read is not strictly bounded before capture. Reviewer should assess whether it merits redesign before merge. Its subprocess timeout is 20 seconds; the job timeout is 2 minutes.
- GitHub-hosted runner IP ranges can change frequently. **Do not blindly restrict port 22 to a narrow IP list**: this could lock out the operator and break connectivity. Any firewall changes require an independently reviewed plan and recovery-console access.
- A passing mocked CI check is **not** a successful real GitHub-to-Hetzner connection, nor proof of absence of trading authority. No real workflow has been dispatched.

## What tests prove

Offline unit tests cover the SSH probe, host-key parsing, nonce/freshness ACK, hostile responses, options to disable forwarding/proxying, initial `0600` file creation and the workflow's required environment reference and distinct secret names. All external SSH attempts are mocked in CI.

**Status:** REVIEW ONLY; not merged, deployed or authorized to run.

```

## File 4: `sender_review/github_to_hetzner_heartbeat_probe_review_only.py`

Git blob: `3cfaf7a6b7e54210dd86961b087f52c9ae822627`

```python
"""One-shot GitHub-runner → Hetzner SSH heartbeat probe. REVIEW ONLY.

No trading APIs or signer. Requires a pinned ED25519 *server host* public key,
a dedicated SSH private key, and manual workflow approval. Does not schedule
work or authorize trades. Never log secrets, key material or raw SSH output.
"""
import base64
import json
import os
import re
import selectors
import secrets
import subprocess
import tempfile
import time
from pathlib import Path

HOST = "2.29.170.69"
USER = "cryptoheartbeat"
_HEX32 = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)


class HeartbeatProbeError(Exception):
    pass


def _pairs_unique(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise HeartbeatProbeError("duplicate ACK field")
        d[k] = v
    return d


def challenge(now, nonce):
    if type(now) is not int or now <= 0 or type(nonce) is not str or not _HEX32.fullmatch(nonce):
        raise HeartbeatProbeError("invalid local challenge")
    return (json.dumps({"v": 1, "kind": "heartbeat", "nonce": nonce, "sent": now},
                       sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def verify_ack(data, *, nonce, now):
    if type(data) is not bytes or not 0 < len(data) <= 500:
        raise HeartbeatProbeError("missing or oversize ACK")
    try:
        ack = json.loads(data.decode("ascii"), object_pairs_hook=_pairs_unique)
    except (ValueError, UnicodeError) as exc:
        raise HeartbeatProbeError("invalid ACK") from exc
    if (type(ack) is not dict
            or set(ack) != {"v", "kind", "nonce", "server_nonce", "received", "authority"}
            or type(ack["v"]) is not int or ack["v"] != 1
            or ack["kind"] != "heartbeat_ack"
            or ack["nonce"] != nonce
            or type(ack["server_nonce"]) is not str
            or not _HEX32.fullmatch(ack["server_nonce"])
            or type(ack["received"]) is not int
            or abs(now - ack["received"]) > 15
            or ack["authority"] != "none"):
        raise HeartbeatProbeError("ACK failed authentication context or freshness checks")
    return True


def pinned_host_key_line(raw):
    """Accept only a trusted ED25519 public host key, never ssh-keyscan output."""
    if type(raw) is not str:
        raise HeartbeatProbeError("missing trusted SSH host key")
    fields = raw.strip().split()
    if len(fields) not in (2, 3) or fields[0] != "ssh-ed25519":
        raise HeartbeatProbeError("expected ssh-ed25519 public host key")
    try:
        blob = base64.b64decode(fields[1], validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise HeartbeatProbeError("invalid trusted host key") from exc
    if len(blob) < 40 or b"ssh-ed25519" not in blob[:20]:
        raise HeartbeatProbeError("malformed host key")
    return HOST + " ssh-ed25519 " + fields[1] + "\n"


def _run_ssh_bounded(args, *, input, capture_output, timeout, check, env=None):
    """Bound SSH stdout to 500 bytes; discard stderr; kill on timeout or excess.

    Avoid subprocess.run(capture_output=True), which buffers untrusted output
    without a cap. This function has no network side effects in offline tests.
    """
    if not capture_output or check or type(input) is not bytes or len(input) > 384:
        raise HeartbeatProbeError("invalid bounded SSH invocation")
    process = subprocess.Popen(
        args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, env=env,
    )
    deadline = time.monotonic() + timeout
    try:
        try:
            process.stdin.write(input)
            process.stdin.close()
        except BrokenPipeError:
            # An SSH setup failure may exit before reading stdin.
            process.stdin.close()
        output = bytearray()
        with selectors.DefaultSelector() as selection:
            selection.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selection.select(remaining):
                    raise subprocess.TimeoutExpired(args, timeout)
                chunk = os.read(process.stdout.fileno(), 501 - len(output))
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > 500:
                    raise HeartbeatProbeError("SSH ACK exceeded maximum length")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(args, timeout)
        code = process.wait(timeout=remaining)
        return subprocess.CompletedProcess(args, code, stdout=bytes(output), stderr=b"")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()


def probe(*, private_key, host_public_key, ssh_run=_run_ssh_bounded, now=None, nonce=None):
    if not isinstance(private_key, str) or not (
        private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
        and private_key.strip().endswith("-----END OPENSSH PRIVATE KEY-----")):
        raise HeartbeatProbeError("SSH key not provided in OpenSSH private-key format")
    known_hosts = pinned_host_key_line(host_public_key)
    start = int(time.time()) if now is None else now
    n = secrets.token_hex(16) if nonce is None else nonce
    frame = challenge(start, n)

    with tempfile.TemporaryDirectory(prefix="heartbeat-review-") as temp:
        key_file = Path(temp) / "identity"
        host_file = Path(temp) / "known_hosts"
        # Avoid creating private material with default permissions before chmod.
        # The new names exist only inside a fresh, private temporary directory.
        for path, contents in ((key_file, private_key.rstrip("\n") + "\n"),
                               (host_file, known_hosts)):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as target:
                target.write(contents)
        args = [
            "ssh", "-T", "-F", "/dev/null", "-p", "22",
            "-i", str(key_file),
            "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "PreferredAuthentications=publickey",
            "-o", "HostKeyAlgorithms=ssh-ed25519",
            "-o", "IdentityAgent=none",
            "-o", "UpdateHostKeys=no",
            "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no",
            "-o", "StrictHostKeyChecking=yes",
            "-o", "UserKnownHostsFile=" + str(host_file),
            "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", "ClearAllForwardings=yes",
            "-o", "ForwardAgent=no",
            "-o", "ControlMaster=no",
            "-o", "ProxyCommand=none",
            "-o", "ProxyJump=none",
            "-o", "RequestTTY=no",
            "-o", "ConnectTimeout=8",
            "-o", "ConnectionAttempts=1",
            "-o", "LogLevel=ERROR",
            USER + "@" + HOST, "heartbeat",
        ]
        try:
            result = ssh_run(args, input=frame, capture_output=True, timeout=20,
                             check=False, env={"PATH": "/usr/bin:/bin", "LANG": "C",
                                               "HOME": temp})
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HeartbeatProbeError("SSH handshake or heartbeat timed out") from exc
    if result.returncode != 0:
        # Do NOT output stderr: may contain host details and unexpected data.
        raise HeartbeatProbeError("SSH probe failed: inspect SSH server logs privately")
    verify_ack(result.stdout, nonce=n, now=int(time.time()) if now is None else now)
    return True


def main():
    try:
        probe(private_key=os.environ.get("HETZNER_HEARTBEAT_SSH_KEY", ""),
              host_public_key=os.environ.get("HETZNER_HEARTBEAT_HOST_KEY_ED25519", ""))
    except HeartbeatProbeError as exc:
        # Fixed, sanitized messages only. Never echo either secret.
        print("SSH HEARTBEAT UNVERIFIED:", str(exc))
        return 1
    print("SSH HEARTBEAT ACK VERIFIED (review-only; trading authority NONE)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

```

## File 5: `sender_review/test_github_to_hetzner_heartbeat_probe_review_only.py`

Git blob: `3209289c42d6888f5ccd56a820ec4798b8418271`

```python
"""Offline tests for GitHub → Hetzner SSH probe; no network or secrets."""
import base64
import json
import os
import stat
import sys
from pathlib import Path
import struct
import subprocess
import unittest
from unittest.mock import patch

from sender_review.github_to_hetzner_heartbeat_probe_review_only import (
    HOST, HeartbeatProbeError, _run_ssh_bounded, challenge, pinned_host_key_line, probe, verify_ack,
)

NOW = 1800000000
NONCE = "a" * 32
def ssh_blob():
    def field(data):
        return struct.pack(">I", len(data)) + data
    return base64.b64encode(field(b"ssh-ed25519") + field(b"\0"*32)).decode("ascii")
HOSTKEY = "ssh-ed25519 " + ssh_blob() + " test"
DUMMY_PRIVATE_KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nDUMMY\n-----END OPENSSH PRIVATE KEY-----"


class GitHubToHetznerProbeReviewTests(unittest.TestCase):
    def test_valid_challenge_and_ack(self):
        frame = json.loads(challenge(NOW, NONCE))
        self.assertEqual(set(frame), {"v", "kind", "nonce", "sent"})
        self.assertEqual(frame["kind"], "heartbeat")
        ack = json.dumps({"v": 1, "kind": "heartbeat_ack", "nonce": NONCE,
                          "server_nonce": "b"*32, "received": NOW,
                          "authority": "none"}).encode("ascii")
        self.assertTrue(verify_ack(ack, nonce=NONCE, now=NOW))

    def test_rejects_wrong_ack_nonce_age_and_authority(self):
        base = {"v": 1, "kind": "heartbeat_ack", "nonce": NONCE,
                "server_nonce": "b"*32, "received": NOW, "authority": "none"}
        for patch_values in (
            {"nonce": "c"*32}, {"received": NOW-16},
            {"received": NOW+16}, {"authority": "trade"},
            {"kind": "trade_ack"}, {"v": True}, {"server_nonce": "invalid"},
            {"action": "buy"}, {"received": 1.0},
        ):
            with self.subTest(case=patch_values), self.assertRaises(HeartbeatProbeError):
                verify_ack(json.dumps({**base, **patch_values}).encode("ascii"),
                           nonce=NONCE, now=NOW)
        with self.assertRaises(HeartbeatProbeError):
            verify_ack(b'{"v":1,"v":1}', nonce=NONCE, now=NOW)

    def test_known_hosts_must_be_fixed_ed25519_key(self):
        self.assertEqual(pinned_host_key_line(HOSTKEY),
                         HOST + " ssh-ed25519 " + ssh_blob() + "\n")
        for invalid in ("", "ssh-rsa " + ssh_blob(),
                        "2.29.170.69 " + HOSTKEY, "ssh-ed25519 garbage", "localhost"):
            with self.subTest(value=invalid), self.assertRaises(HeartbeatProbeError):
                pinned_host_key_line(invalid)

    def test_probe_uses_pinned_host_and_no_tty_or_forwarding(self):
        inspected = []
        def fake_run(args, **kwargs):
            inspected.append((args, kwargs))
            outgoing = json.loads(kwargs["input"])
            self.assertEqual(outgoing["nonce"], NONCE)
            self.assertIn("StrictHostKeyChecking=yes", args)
            self.assertIn("ClearAllForwardings=yes", args)
            self.assertIn("BatchMode=yes", args)
            self.assertIn("-T", args)
            self.assertNotIn("StrictHostKeyChecking=no", args)
            self.assertIn("ProxyCommand=none", args)
            self.assertIn("ProxyJump=none", args)
            self.assertIn("RequestTTY=no", args)
            self.assertIn('HostKeyAlgorithms=ssh-ed25519', args)
            self.assertIn('IdentityAgent=none', args)
            self.assertIn('UpdateHostKeys=no', args)
            self.assertIn('-F', args)
            self.assertEqual(args[args.index('-F')+1], '/dev/null')
            key_path = Path(args[args.index("-i") + 1])
            self.assertEqual(stat.S_IMODE(key_path.stat().st_mode), 0o600)
            host_opt = next(x for x in args if x.startswith("UserKnownHostsFile="))
            host_path = Path(host_opt.partition("=")[2])
            self.assertEqual(stat.S_IMODE(host_path.stat().st_mode), 0o600)
            reply = json.dumps({"v": 1, "kind": "heartbeat_ack",
                                "nonce": NONCE, "server_nonce": "b"*32,
                                "received": NOW, "authority": "none"}).encode("ascii")
            return subprocess.CompletedProcess(args, 0, stdout=reply, stderr=b"")
        self.assertTrue(probe(private_key=DUMMY_PRIVATE_KEY,
                              host_public_key=HOSTKEY, ssh_run=fake_run,
                              now=NOW, nonce=NONCE))
        self.assertEqual(len(inspected), 1)

    def test_review_workflow_requires_separate_environment_secrets(self):
        """No original repo-secret names and no unprotected heartbeat job."""
        wf = Path('.github/workflows/manual-hetzner-ssh-heartbeat-review.yml').read_text()
        self.assertIn('environment: hetzner-heartbeat-review', wf)
        self.assertIn("github.ref == 'refs/heads/main'", wf)
        self.assertIn("inputs.confirm == 'RUN_READONLY_HEARTBEAT'", wf)
        self.assertIn('secrets.HETZNER_HEARTBEAT_REVIEW_ENV_PRIVATE_KEY', wf)
        self.assertIn('secrets.HETZNER_HEARTBEAT_REVIEW_ENV_HOST_KEY_ED25519', wf)
        self.assertNotIn('secrets.HETZNER_HEARTBEAT_SSH_KEY', wf)
        self.assertNotIn('secrets.HETZNER_HEARTBEAT_HOST_KEY_ED25519', wf)
        self.assertNotIn('on: push', wf)
        self.assertNotIn('on: schedule', wf)

    def test_bounded_local_process_captures_small_ack(self):
        # Local python process only, never an SSH/network connection.
        p = [sys.executable, '-c',
             'import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b"OK")']
        r = _run_ssh_bounded(p, input=b"hello", capture_output=True, timeout=3,
                             check=False)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, b"OK")

    def test_bounded_local_process_rejects_overflow(self):
        p = [sys.executable, '-c',
             'import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b"x"*501); sys.stdout.flush()']
        with self.assertRaisesRegex(HeartbeatProbeError, "maximum length"):
            _run_ssh_bounded(p, input=b"hello", capture_output=True, timeout=3,
                             check=False)

    def test_bounded_local_process_times_out(self):
        p = [sys.executable, '-c',
             'import time,sys; sys.stdin.buffer.read(); time.sleep(3)']
        with self.assertRaises(subprocess.TimeoutExpired):
            _run_ssh_bounded(p, input=b"hello", capture_output=True, timeout=0.3,
                             check=False)

    def test_nonzero_exit_never_echoes_stderr(self):
        def failed_run(args, **kw):
            return subprocess.CompletedProcess(args, 255, stdout=b"",
                                               stderr=b"DO_NOT_LOG_SECRET")
        with self.assertRaisesRegex(HeartbeatProbeError,
                                    "SSH probe failed"):
            probe(private_key=DUMMY_PRIVATE_KEY, host_public_key=HOSTKEY,
                  ssh_run=failed_run, now=NOW, nonce=NONCE)

    def test_no_network_when_input_missing(self):
        with patch("sender_review.github_to_hetzner_heartbeat_probe_review_only.subprocess.run",
                   side_effect=AssertionError("network not allowed")):
            with self.assertRaises(HeartbeatProbeError):
                probe(private_key="", host_public_key=HOSTKEY)


if __name__ == "__main__":
    unittest.main()

```

