"""Wire six UNTRUSTED synthetic /info payloads to the HOLD reconciliation.

No network, HTTP client, TLS, keys, credentials, signer, DB or host I/O.
A caller can forge any payload, request, status and step label here.
This catches wiring/configuration mistakes in offline fixtures, never proves
exchange provenance, complete history, ownership or safe trading.
"""
from dataclasses import dataclass
import hashlib
import json
from decimal import Decimal

from sender_review.hyperliquid_readonly_collection_plan_offline import (
    plan_offline_six_frame_reconciliation_fixture,
)
from sender_review.coordinated_testnet_readset_review import (
    inspect_coordinated_readset_offline,
)
from sender_review.signer_free_account_view_offline import (
    extract_signer_free_account_view_offline,
)

_MAX_RESPONSE_BYTES = 524_288


@dataclass(frozen=True)
class SyntheticInfoFrame:
    step: int
    scheme: str
    host: str
    method: str
    path: str
    content_type: str
    request_body: bytes
    claimed_status_code: int
    response_body: bytes


@dataclass(frozen=True)
class OfflinePayloadBindingReview:
    state: str = "HOLD"
    reason: str = "no authenticated origin for synthetic responses"
    exact_synthetic_wiring: bool = False
    locally_consistent: bool = False
    # A coherent six-frame history sample can still lack the complete
    # data shape required by the legacy strategies. This local check is
    # NEVER trusted exchange provenance, risk clearance or trade authority.
    strategy_shape_compatible: bool = False
    additional_spot_read_needed: bool = False
    observed_request_sha256: tuple[str, ...] = ()
    observed_response_sha256: tuple[str, ...] = ()
    frames_reviewed: int = 0
    network_performed: bool = False
    authenticated_tls_origin: bool = False
    authenticated_response_provenance: bool = False
    account_identity_verified: bool = False
    historical_coverage_verified: bool = False
    position_ownership_verified: bool = False
    durable_fence_reserved: bool = False
    submit_authorized: bool = False
    close_authorized: bool = False
    signing_enabled: bool = False


def _unique_pairs(pairs):
    parsed = {}
    for key, value in pairs:
        if key in parsed:
            raise ValueError("duplicate response key")
        parsed[key] = value
    return parsed


def _reject_constant(_value):
    raise ValueError("non-finite response JSON")


def inspect_synthetic_info_payload_binding_offline(
    *, account, start_time_ms, end_time_ms, frames,
):
    """Inspect an exact six-request/six-response fixture, ALWAYS HOLD.

    The returned hashes only identify locally supplied bytes. They do not
    authenticate their origin and MUST NOT be consumed as a network or trade
    authorization decision.
    """
    held = OfflinePayloadBindingReview()
    plan = plan_offline_six_frame_reconciliation_fixture(
        account=account, start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
    )
    if (len(plan.queries) != 6 or type(frames) is not tuple
            or len(frames) != 6):
        return held
    documents = []
    request_digests = []
    response_digests = []
    for step, (query, frame) in enumerate(zip(plan.queries, frames), 1):
        if type(frame) is not SyntheticInfoFrame:
            return OfflinePayloadBindingReview(reason="invalid frame")
        if (
            type(frame.step) is not int or frame.step != step
            or type(frame.scheme) is not str or frame.scheme != query.scheme
            or type(frame.host) is not str or frame.host != query.host
            or type(frame.method) is not str or frame.method != query.method
            or type(frame.path) is not str or frame.path != query.path
            or type(frame.content_type) is not str
            or frame.content_type != query.content_type
            or type(frame.request_body) is not bytes
            or frame.request_body != query.body_json.encode("ascii")
            or type(frame.claimed_status_code) is not int
            or frame.claimed_status_code != 200
            or type(frame.response_body) is not bytes
            or not 0 < len(frame.response_body) <= _MAX_RESPONSE_BYTES
        ):
            return OfflinePayloadBindingReview(
                reason="wrong request step, destination, body, status or size"
            )
        try:
            doc = json.loads(
                frame.response_body.decode("utf-8"),
                object_pairs_hook=_unique_pairs,
                parse_constant=_reject_constant,
            )
        except (UnicodeError, TypeError, ValueError, OverflowError):
            return OfflinePayloadBindingReview(
                reason="invalid or ambiguous fixture response JSON"
            )
        if type(doc) not in (list, dict):
            return OfflinePayloadBindingReview(
                reason="unexpected response document type"
            )
        documents.append(doc)
        request_digests.append(hashlib.sha256(frame.request_body).hexdigest())
        response_digests.append(hashlib.sha256(frame.response_body).hexdigest())

    result = inspect_coordinated_readset_offline(
        positions_before=documents[0],
        open_orders_before=documents[1],
        historical_orders=documents[2],
        user_fills=documents[3],
        open_orders_after=documents[4],
        positions_after=documents[5],
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
    )
    # Separate diagnostic: the six history/position frames may be locally
    # consistent while lacking margin/equity or market fields required by
    # the Daily/Intraday/Aggressive strategy readers. Do not elevate that
    # weaker reconciliation verdict into a usable strategy account view.
    before_view = extract_signer_free_account_view_offline(
        user_state=documents[0],
    )
    after_view = extract_signer_free_account_view_offline(
        user_state=documents[5],
    )
    needs_spot = (
        before_view.additional_spot_read_needed
        or after_view.additional_spot_read_needed
    )
    strategy_shape_compatible = (
        result.locally_consistent
        and before_view.fixture_parsed is True
        and after_view.fixture_parsed is True
        and before_view.positions == after_view.positions
        and before_view.equity == after_view.equity
        # The legacy shape uses floats. Do not mistake sub-ULP changes
        # in a decimal exchange snapshot for a stable account bookend.
        and Decimal(str(documents[0]["marginSummary"]["accountValue"]))
            == Decimal(str(documents[5]["marginSummary"]["accountValue"]))
        and documents[0]["assetPositions"] == documents[5]["assetPositions"]
        and not needs_spot
    )
    return OfflinePayloadBindingReview(
        reason="six fixture bodies wired locally; " + result.reason
               + "; exchange origin and operator approval absent",
        exact_synthetic_wiring=True,
        locally_consistent=result.locally_consistent,
        strategy_shape_compatible=strategy_shape_compatible,
        additional_spot_read_needed=needs_spot,
        observed_request_sha256=tuple(request_digests),
        observed_response_sha256=tuple(response_digests),
        frames_reviewed=6,
    )
