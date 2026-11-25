"""Manual GitHub-to-Hetzner SSH liveness probe. NEVER trading authority.

Only invoked by a separately approved, manual GitHub Actions dispatch on main.
No Hyperliquid/DB imports, account control, persistent service or remote shell.
Host/IP and remote account are fixed. Auth uses the dedicated heartbeat SSH
private key; the host identity uses a separately stored ED25519 public key.
No SSH secrets, raw responses or auth material are printed.
"""
import base64
import json
import os
from pathlib import Path
import re
import secrets
import struct
import subprocess
import tempfile
import time

HOST = "2.29.170.69"
USER = "cryptoheartbeat"
HEX32 = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)


class HeartbeatHold(ValueError):
    pass


def pinned_known_hosts_line(value):
    """Accept only one direct ED25519 host key for the fixed server IP."""
    if not isinstance(value, str) or not 10 < len(value) < 800:
        raise HeartbeatHold("host key absent or invalid")
    if any(c in value for c in "\r\n\0"):
        raise HeartbeatHold("ambiguous host key")
    words = value.strip().split()
    if len(words) < 2:
        raise HeartbeatHold("host key incomplete")
    if words[0] == "ssh-ed25519":
        encoded = words[1]
    elif len(words) >= 3 and words[0] == HOST and words[1] == "ssh-ed25519":
        encoded = words[2]
    else:
        raise HeartbeatHold("host or algorithm mismatch")
    try:
        blob = base64.b64decode(encoded, validate=True)
        offset = 0
        fields = []
        for _ in range(2):
            if len(blob) < offset + 4:
                raise ValueError("short SSH field")
            count = struct.unpack(">I", blob[offset:offset+4])[0]
            offset += 4
            if count > 64 or len(blob) < offset + count:
                raise ValueError("invalid SSH field")
            fields.append(blob[offset:offset+count])
            offset += count
        if offset != len(blob) or fields[0] != b"ssh-ed25519" or len(fields[1]) != 32:
            raise ValueError("not ED25519 SSH host public key")
    except (ValueError, struct.error) as exc:
        raise HeartbeatHold("invalid pinned ED25519 host key") from exc
    return f"{HOST} ssh-ed25519 {encoded}\n"


def challenge(now, nonce):
    if type(now) is not int or now <= 0 or type(nonce) is not str or not HEX32.fullmatch(nonce):
        raise HeartbeatHold("invalid heartbeat inputs")
    return (json.dumps(
        {"v": 1, "kind": "heartbeat", "nonce": nonce, "sent": now},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ) + "\n").encode("ascii")


def check_ack(raw, *, nonce, now):
    """Validate one matching response, never infer trade authorization."""
    if type(raw) is not bytes or not 10 <= len(raw) <= 512:
        raise HeartbeatHold("invalid heartbeat response size")
    if raw.count(b"\n") != 1 or not raw.endswith(b"\n"):
        raise HeartbeatHold("invalid heartbeat framing")
    def unique_pairs(pairs):
        found = {}
        for key, value in pairs:
            if key in found:
                raise HeartbeatHold("duplicate heartbeat field")
            found[key] = value
        return found
    try:
        obj = json.loads(raw.decode("ascii"), object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeError) as exc:
        raise HeartbeatHold("invalid heartbeat ACK") from exc
    if (type(obj) is not dict
        or set(obj) != {"v", "kind", "nonce", "server_nonce", "received", "authority"}
        or type(obj["v"]) is not int or obj["v"] != 1
        or obj["kind"] != "heartbeat_ack"
        or obj["nonce"] != nonce
        or type(obj["server_nonce"]) is not str
        or HEX32.fullmatch(obj["server_nonce"]) is None
        or type(obj["received"]) is not int
        or abs(obj["received"] - now) > 10
        or obj["authority"] != "none"):
        raise HeartbeatHold("mismatched, stale or non-liveness ACK")
    return True


def _write_private_key(path, value):
    # Never print or parse the key with a shell. The runner dir is ephemeral.
    if not isinstance(value, str) or not value.startswith("-----BEGIN OPENSSH PRIVATE KEY-----") \
       or "-----END OPENSSH PRIVATE KEY-----" not in value or len(value) > 20000:
        raise HeartbeatHold("dedicated SSH private key missing or invalid")
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(value.rstrip("\n") + "\n")


def _ssh_failure_category(stderr):
    """Classify SSH failure without emitting attacker-controlled stderr.

    Never log raw SSH diagnostics, private key content, or peer responses.
    """
    if type(stderr) is not bytes:
        return "SSH_FAILED_UNCLASSIFIED"
    if (b"Host key verification failed" in stderr
            or b"REMOTE HOST IDENTIFICATION HAS CHANGED" in stderr):
        return "SSH_HOST_KEY_REJECTED"
    if (b"Load key" in stderr or b"sign_and_send_pubkey" in stderr
            or b"invalid format" in stderr):
        return "SSH_PRIVATE_KEY_UNUSABLE"
    if b"Permission denied" in stderr:
        return "SSH_AUTHENTICATION_REJECTED"
    if b"Connection refused" in stderr:
        return "SSH_CONNECTION_REFUSED"
    if (b"timed out" in stderr or b"Network is unreachable" in stderr
            or b"No route to host" in stderr):
        return "SSH_NETWORK_UNAVAILABLE"
    return "SSH_FAILED_UNCLASSIFIED"


def main():
    # Defense in depth; workflow is also gated by dispatch input and main ref.
    if (os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or os.environ.get("HEARTBEAT_MANUAL_CONFIRM") != "yes"):
        raise HeartbeatHold("DISPATCH_GUARD_REJECTED")
    key = os.environ.get("HETZNER_HEARTBEAT_SSH_KEY", "")
    try:
        host_key = pinned_known_hosts_line(
            os.environ.get("HETZNER_HEARTBEAT_HOST_KEY_ED25519", "")
        )
    except HeartbeatHold as exc:
        raise HeartbeatHold("HOST_KEY_SECRET_INVALID") from exc
    nonce = secrets.token_hex(16)
    now = int(time.time())
    data = challenge(now, nonce)
    with tempfile.TemporaryDirectory(prefix="hetzner-heartbeat-") as temp:
        folder = Path(temp)
        key_path, host_path = folder / "id_ed25519", folder / "known_hosts"
        try:
            _write_private_key(key_path, key)
        except (HeartbeatHold, UnicodeError) as exc:
            raise HeartbeatHold("PRIVATE_KEY_SECRET_INVALID") from exc
        host_path.write_text(host_key, encoding="ascii")
        host_path.chmod(0o600)
        cmd = [
            "ssh", "-F", "/dev/null", "-p", "22", "-i", str(key_path),
            "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={host_path}",
            "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no",
            "-o", "ConnectTimeout=6", "-o", "ConnectionAttempts=1",
            "-o", "RequestTTY=no", "-o", "ClearAllForwardings=yes",
            "-o", "ForwardAgent=no", "-o", "PermitLocalCommand=no",
            "-o", "ControlMaster=no", f"{USER}@{HOST}",
        ]
        try:
            response = subprocess.run(
                cmd, input=data, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=16, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HeartbeatHold("SSH_TRANSPORT_UNAVAILABLE") from exc
    if response.returncode != 0:
        raise HeartbeatHold(_ssh_failure_category(response.stderr))
    try:
        check_ack(response.stdout, nonce=nonce, now=int(time.time()))
    except HeartbeatHold as exc:
        raise HeartbeatHold("HEARTBEAT_ACK_REJECTED") from exc
    print("HEARTBEAT ACK VERIFIED — LIVENESS ONLY; NO TRADE AUTHORITY")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except HeartbeatHold as exc:
        # These fixed, source-authored categories never contain secrets,
        # arbitrary SSH output, private keys, or untrusted peer data.
        code = str(exc)
        allowed = {
            "DISPATCH_GUARD_REJECTED", "HOST_KEY_SECRET_INVALID",
            "PRIVATE_KEY_SECRET_INVALID", "SSH_TRANSPORT_UNAVAILABLE",
            "SSH_HOST_KEY_REJECTED", "SSH_PRIVATE_KEY_UNUSABLE",
            "SSH_AUTHENTICATION_REJECTED", "SSH_CONNECTION_REFUSED",
            "SSH_NETWORK_UNAVAILABLE", "SSH_FAILED_UNCLASSIFIED",
            "HEARTBEAT_ACK_REJECTED",
        }
        if code not in allowed:
            code = "HEARTBEAT_HOLD_UNKNOWN"
        print("HEARTBEAT HOLD: " + code + " — NO TRADE AUTHORITY")
        raise SystemExit(1)
