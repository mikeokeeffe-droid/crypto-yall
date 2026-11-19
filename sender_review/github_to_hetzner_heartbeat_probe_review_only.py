"""One-shot GitHub-runner → Hetzner SSH heartbeat probe. REVIEW ONLY.

No trading APIs or signer. Requires a pinned ED25519 *server host* public key,
a dedicated SSH private key, and manual workflow approval. Does not schedule
work or authorize trades. Never log secrets, key material or raw SSH output.
"""
import base64
import json
import os
import re
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


def probe(*, private_key, host_public_key, ssh_run=subprocess.run, now=None, nonce=None):
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
        key_file.write_text(private_key.rstrip("\n") + "\n", encoding="ascii")
        host_file.write_text(known_hosts, encoding="ascii")
        key_file.chmod(0o600)
        host_file.chmod(0o600)
        args = [
            "ssh", "-T", "-p", "22",
            "-i", str(key_file),
            "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "PreferredAuthentications=publickey",
            "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no",
            "-o", "StrictHostKeyChecking=yes",
            "-o", "UserKnownHostsFile=" + str(host_file),
            "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", "ClearAllForwardings=yes",
            "-o", "ForwardAgent=no",
            "-o", "ControlMaster=no",
            "-o", "ConnectTimeout=8",
            "-o", "ConnectionAttempts=1",
            "-o", "LogLevel=ERROR",
            USER + "@" + HOST, "heartbeat",
        ]
        try:
            result = ssh_run(args, input=frame, capture_output=True, timeout=20,
                             check=False)
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
