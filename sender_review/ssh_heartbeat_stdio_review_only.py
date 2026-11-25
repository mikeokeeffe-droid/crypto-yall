"""Review-only SSH forced-command heartbeat responder (no network listener).

This script reads one exact JSON heartbeat from stdin and emits one JSON ACK.
It MUST only ever be reached through a separately approved, pinned-host-key
SSH transport with a DEDICATED no-shell restricted user and forced command.
The script itself does NOT authenticate the caller or make a secure channel.
Not deployed or wired to any live workflow. It has no trade API, DB, network,
exchange client, credential access, durable replay ledger or authorization.
"""
import json
import re
import secrets
import sys
import time

_HEX = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_MAX_INPUT = 384
_MAX_SKEW_SECONDS = 10


class InvalidHeartbeat(ValueError):
    pass


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidHeartbeat("duplicate heartbeat key")
        result[key] = value
    return result


def make_review_ack(raw, *, now, random_hex=None):
    """Validate a one-off liveness challenge; never grant trading permission.

    SSH peer authentication, host-key pinning, replay resistance between
    connections and runtime isolation are EXTERNAL requirements. This
    ACK must never be accepted as execution authorization.
    """
    if type(raw) is not bytes or not 0 < len(raw) <= _MAX_INPUT:
        raise InvalidHeartbeat("invalid heartbeat frame length")
    if type(now) is not int or now <= 0:
        raise InvalidHeartbeat("invalid server clock")
    try:
        request = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeError) as exc:
        raise InvalidHeartbeat("invalid heartbeat JSON") from exc
    if (type(request) is not dict
            or set(request) != {"v", "kind", "nonce", "sent"}
            or type(request["v"]) is not int or request["v"] != 1
            or request["kind"] != "heartbeat"
            or type(request["nonce"]) is not str
            or _HEX.fullmatch(request["nonce"]) is None
            or type(request["sent"]) is not int
            or abs(now - request["sent"]) > _MAX_SKEW_SECONDS):
        raise InvalidHeartbeat("invalid or stale heartbeat")
    if random_hex is None:
        random_hex = secrets.token_hex(16)
    if type(random_hex) is not str or _HEX.fullmatch(random_hex) is None:
        raise InvalidHeartbeat("invalid server challenge")
    response = {
        "v": 1,
        "kind": "heartbeat_ack",
        "nonce": request["nonce"],
        "server_nonce": random_hex,
        "received": now,
        "authority": "none",
    }
    return (json.dumps(response, sort_keys=True,
                       separators=(",", ":"), ensure_ascii=True)
            + "\n").encode("ascii")


def main():
    # Fail-closed read bound; never log raw requests, secrets or exception data.
    raw = sys.stdin.buffer.readline(_MAX_INPUT + 2)
    try:
        if not raw.endswith(b"\n") or len(raw) > _MAX_INPUT + 1:
            raise InvalidHeartbeat("missing or oversized newline-terminated frame")
        if not raw[:-1] or b"\n" in raw[:-1]:
            raise InvalidHeartbeat("invalid heartbeat framing")
        ack = make_review_ack(raw[:-1], now=int(time.time()))
    except (InvalidHeartbeat, OSError, OverflowError, TypeError):
        print("HEARTBEAT_REJECTED", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(ack)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
