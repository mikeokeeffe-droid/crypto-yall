"""Heartbeat-only link protocol candidate. No listener, network, secrets or trades.

An ACK here proves only that a party with the separately provisioned link
secret saw a particular fresh heartbeat. It never authenticates a trade or
grants order authority. In-memory replay state is NOT durable across restarts.
This code is REVIEW-ONLY and has no caller in any existing bot.
"""
from dataclasses import dataclass
import hashlib
import hmac
import json
import re

_HEX32 = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_MAX_BYTES = 512
_MAX_SKEW_SEC = 10
_MAX_SESSIONS = 32
_MAX_SEQ = (1 << 53) - 1


class HeartbeatRejected(ValueError):
    pass


def _secret(key):
    if type(key) is not bytes or len(key) < 32:
        raise HeartbeatRejected("link key must be separately provisioned")


def _checked_hex(s):
    return type(s) is str and _HEX32.fullmatch(s) is not None


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _mac(key, payload):
    return hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()


def _parse(raw, fields):
    if type(raw) is not bytes or len(raw) > _MAX_BYTES:
        raise HeartbeatRejected("oversize or invalid heartbeat frame")
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise HeartbeatRejected("duplicate JSON key")
            result[k] = v
        return result
    try:
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise HeartbeatRejected("invalid JSON") from exc
    if type(body) is not dict or set(body) != fields:
        raise HeartbeatRejected("unexpected heartbeat fields")
    if type(body["v"]) is not int or body["v"] != 1:
        raise HeartbeatRejected("unknown heartbeat version")
    if not (_checked_hex(body["boot"]) and _checked_hex(body["nonce"])
            and type(body["seq"]) is int and 0 < body["seq"] <= _MAX_SEQ
            and type(body["mac"]) is str
            and len(body["mac"]) == 64
            and re.fullmatch(r"[0-9a-f]{64}", body["mac"]) is not None):
        raise HeartbeatRejected("invalid heartbeat identity/sequence")
    return body


_REQUEST_FIELDS = frozenset({"v", "kind", "boot", "seq", "nonce", "sent", "mac"})
_ACK_FIELDS = frozenset({"v", "kind", "boot", "seq", "nonce", "recv", "mac"})


def create_probe(*, key, boot, seq, nonce, now):
    """Caller must use cryptographically random boot and nonce per process/send."""
    _secret(key)
    if (not _checked_hex(boot) or not _checked_hex(nonce)
            or type(seq) is not int or not 0 < seq <= _MAX_SEQ
            or type(now) is not int or now <= 0):
        raise HeartbeatRejected("invalid probe inputs")
    data = {"v": 1, "kind": "heartbeat", "boot": boot,
            "seq": seq, "nonce": nonce, "sent": now}
    return _canonical({**data, "mac": _mac(key, data)})


class HeartbeatReceiver:
    """Review-only in-memory replay protection; DO NOT use to grant trade access."""

    def __init__(self, *, key):
        _secret(key)
        self._key = key
        self._seen = {}

    def receive(self, *, probe, now):
        if type(now) is not int or now <= 0:
            raise HeartbeatRejected("invalid receiver clock")
        body = _parse(probe, _REQUEST_FIELDS)
        if body["kind"] != "heartbeat" or type(body["sent"]) is not int:
            raise HeartbeatRejected("not a heartbeat")
        if abs(now - body["sent"]) > _MAX_SKEW_SEC:
            raise HeartbeatRejected("stale heartbeat")
        supplied = body.pop("mac")
        if not hmac.compare_digest(_mac(self._key, body), supplied):
            raise HeartbeatRejected("invalid heartbeat MAC")
        previous = self._seen.get(body["boot"], 0)
        if body["seq"] <= previous:
            raise HeartbeatRejected("replayed heartbeat")
        if body["boot"] not in self._seen and len(self._seen) >= _MAX_SESSIONS:
            raise HeartbeatRejected("too many sessions; fail closed")
        self._seen[body["boot"]] = body["seq"]
        ack = {"v": 1, "kind": "heartbeat_ack", "boot": body["boot"],
               "seq": body["seq"], "nonce": body["nonce"], "recv": now}
        return _canonical({**ack, "mac": _mac(self._key, ack)})


@dataclass(frozen=True)
class HeartbeatStatus:
    connected: bool = False
    last_rtt_ms: int | None = None
    reason: str = "no acknowledged heartbeat"


class HeartbeatObserver:
    """Report connection health only. Neither ACK nor health permits an order."""

    def __init__(self, *, key, timeout_seconds=6.0, max_rtt_seconds=2.0):
        _secret(key)
        if (type(timeout_seconds) not in (int, float)
                or not 0 < timeout_seconds <= 60
                or type(max_rtt_seconds) not in (int, float)
                or not 0 < max_rtt_seconds < timeout_seconds):
            raise HeartbeatRejected("invalid observer thresholds")
        self._key = key
        self._timeout = float(timeout_seconds)
        self._max_rtt = float(max_rtt_seconds)
        self._last_ack = None
        self._last_rtt_ms = None
        self._last_seq = 0
        self._boot = None

    def acknowledge(self, *, probe, ack, now, sent_monotonic, recv_monotonic):
        request = _parse(probe, _REQUEST_FIELDS)
        response = _parse(ack, _ACK_FIELDS)
        rtt = recv_monotonic - sent_monotonic
        if (type(now) is not int or now <= 0
                or type(sent_monotonic) not in (int, float)
                or type(recv_monotonic) not in (int, float)
                or not 0 <= rtt <= self._max_rtt):
            raise HeartbeatRejected("slow or invalid acknowledgement")
        if (response["kind"] != "heartbeat_ack"
                or type(response["recv"]) is not int
                or abs(now - response["recv"]) > _MAX_SKEW_SEC
                or request["kind"] != "heartbeat"
                or type(request["sent"]) is not int
                or abs(now - request["sent"]) > _MAX_SKEW_SEC
                or response["boot"] != request["boot"]
                or response["nonce"] != request["nonce"]
                or response["seq"] != request["seq"]):
            raise HeartbeatRejected("wrong acknowledgement")
        request_mac = request.pop("mac")
        ack_mac = response.pop("mac")
        if (not hmac.compare_digest(_mac(self._key, request), request_mac)
                or not hmac.compare_digest(_mac(self._key, response), ack_mac)):
            raise HeartbeatRejected("wrong heartbeat MAC")
        if self._boot == request["boot"] and request["seq"] <= self._last_seq:
            raise HeartbeatRejected("replayed acknowledgement")
        if self._boot != request["boot"]:
            # A new sender boot cannot simply overwrite a confirmed identity.
            if self._boot is not None:
                raise HeartbeatRejected("boot change requires new observer")
            self._boot = request["boot"]
        self._last_seq = request["seq"]
        self._last_ack = float(recv_monotonic)
        self._last_rtt_ms = round(rtt * 1000)
        return HeartbeatStatus(True, self._last_rtt_ms, "observed only; no trade authority")

    def status(self, *, now_monotonic):
        if type(now_monotonic) not in (int, float):
            raise HeartbeatRejected("invalid monotonic clock")
        if self._last_ack is None:
            return HeartbeatStatus()
        if now_monotonic < self._last_ack:
            return HeartbeatStatus(False, self._last_rtt_ms, "clock/reset uncertainty")
        if now_monotonic - self._last_ack > self._timeout:
            return HeartbeatStatus(False, self._last_rtt_ms, "heartbeat timeout")
        return HeartbeatStatus(True, self._last_rtt_ms,
                               "observed only; no trade authority")
