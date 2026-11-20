"""Six fixed Hyperliquid TESTNET /info query frames, SYNTHETIC REVIEW ONLY.

This is a pure, in-process data-shape fixture, not a transport, executable
gateway, trusted account validator, complete history checker or authorization.
No HTTP client, network, signer, exchange SDK, secrets, database or host I/O.
The real PR #41 collector entrypoint stays permanently disabled. A future
gateway requires a separate reviewed implementation and explicit approval.
"""
from dataclasses import dataclass
import hashlib
import json
import re

HOST = "api.hyperliquid-testnet.xyz"
PATH = "/info"
METHOD = "POST"
ENDPOINT = "https://" + HOST + PATH
FIXTURE_ACCOUNT = "0x" + "1" * 40  # Synthetic test ID, NOT operator approval.
_MS_MAX = 9007199254740991
_WINDOW_LIMIT_MS = 86_400_000
_ACCOUNT = re.compile(r"0x[0-9a-f]{40}\Z", re.ASCII)
_TYPES = (
    "clearinghouseState", "openOrders", "historicalOrders",
    "userFillsByTime", "openOrders", "clearinghouseState",
)


@dataclass(frozen=True)
class OfflineReadFrame:
    step: int
    kind: str
    method: str
    path: str
    body: bytes
    body_sha256: str


@dataclass(frozen=True)
class OfflineSixFrameReview:
    # Always HOLD; "matching" is local syntax only, never trust/authorization.
    state: str = "HOLD"
    reason: str = "no independently approved testnet collector"
    frames: tuple[OfflineReadFrame, ...] = ()
    matches_fixture: bool = False
    network_performed: bool = False
    origin_authenticated: bool = False
    history_complete: bool = False
    position_ownership_verified: bool = False
    request_authorized: bool = False
    order_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def _canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("ascii")


def plan_synthetic_six_frame_readset_offline(*, account, start_ms, end_ms):
    """Describe six *untrusted* fixture requests; never perform/allow them.

    No one can designate a real account with this API. The real operator-
    approved scope and any runtime authorization must be defined elsewhere,
    after independent security review, and must not call this module as a gate.
    """
    hold = OfflineSixFrameReview()
    if (type(account) is not str or _ACCOUNT.fullmatch(account) is None
            or account != FIXTURE_ACCOUNT
            or type(start_ms) is not int or type(end_ms) is not int
            or not 0 < start_ms < end_ms <= _MS_MAX
            or end_ms - start_ms > _WINDOW_LIMIT_MS):
        return hold
    bodies = (
        {"type": "clearinghouseState", "user": account, "dex": ""},
        {"type": "openOrders", "user": account, "dex": ""},
        {"type": "historicalOrders", "user": account},
        {"type": "userFillsByTime", "user": account,
         "startTime": start_ms, "endTime": end_ms,
         "aggregateByTime": False},
        {"type": "openOrders", "user": account, "dex": ""},
        {"type": "clearinghouseState", "user": account, "dex": ""},
    )
    frames = tuple(
        OfflineReadFrame(
            step=index,
            kind=expected,
            method=METHOD,
            path=PATH,
            body=(wire := _canonical(body)),
            body_sha256=hashlib.sha256(wire).hexdigest(),
        )
        for index, (expected, body) in enumerate(zip(_TYPES, bodies), start=1)
    )
    return OfflineSixFrameReview(
        reason="exactly six synthetic /info frames; origin, history, "
               "identity, position ownership and all approval absent",
        frames=frames,
        matches_fixture=True,
    )


def inspect_synthetic_frame_offline(
    *, account, start_ms, end_ms, step, method, path, body,
):
    """Reject any noncanonical frame, including alternate path or extra keys.

    This diagnostic always returns HOLD and makes no network request.
    A matched synthetic plan must NEVER be used to enable an HTTP call.
    """
    planned = plan_synthetic_six_frame_readset_offline(
        account=account, start_ms=start_ms, end_ms=end_ms,
    )
    if (not planned.matches_fixture or type(step) is not int
            or not 1 <= step <= 6 or type(method) is not str
            or type(path) is not str or type(body) is not bytes):
        return OfflineSixFrameReview(reason="invalid scope or frame")
    expected = planned.frames[step - 1]
    if method != METHOD or path != PATH or body != expected.body:
        return OfflineSixFrameReview(reason="unexpected frame, route or bytes")
    return OfflineSixFrameReview(
        reason="matching synthetic frame only; no network or authority",
        matches_fixture=True,
    )
