"""Synthetic-only pipeline: no trading authorization or network operations.

The pipeline's only possible statuses are 'hold' and 'review_only'.
Caller-supplied HTTP and timing metadata is NOT authenticated evidence.
"""
from dataclasses import dataclass
from offline_hyperliquid_http_envelope import inspect_http_envelope_offline
from offline_hyperliquid_json_boundary import inspect_json_payload_offline
from offline_hyperliquid_evidence_freshness import inspect_evidence_freshness_offline
from offline_hyperliquid_wire_review import (
    parse_order_status_offline, parse_fills_by_time_offline,
)
from offline_hyperliquid_order_fill_conflicts import inspect_order_fill_consistency_offline
from offline_hyperliquid_account_impact import inspect_account_order_impact_offline

@dataclass(frozen=True)
class PipelineReview:
    status: str
    reason: str

def inspect_synthetic_order_pipeline_offline(*, order_bytes, fills_bytes,
    order_request, fills_request, account, coin, oid, direction, size,
    submitted_at_ms, start_ms, end_ms, http_envelopes, capture_times,
    open_orders_known_empty=False, position_snapshot_verified=False):
    def hold(reason):
        return PipelineReview("hold", reason)
    if type(http_envelopes) is not tuple or len(http_envelopes) != 2:
        return hold("both HTTP envelopes required")
    for envelope in http_envelopes:
        if type(envelope) is not dict:
            return hold("invalid HTTP envelope")
        try:
            review = inspect_http_envelope_offline(**envelope)
        except TypeError:
            return hold("invalid HTTP envelope arguments")
        if review.status != "review_only":
            return hold("HTTP envelope failed policy")
    if type(capture_times) is not tuple or len(capture_times) != 2:
        return hold("both capture timelines required")
    for timeline in capture_times:
        if type(timeline) is not dict:
            return hold("invalid capture timeline")
        try:
            review = inspect_evidence_freshness_offline(**timeline)
        except TypeError:
            return hold("invalid capture timing arguments")
        if review.status != "review_only":
            return hold("capture timing failed policy")
    order_json = inspect_json_payload_offline(raw=order_bytes, kind="orderStatus")
    fills_json = inspect_json_payload_offline(raw=fills_bytes, kind="userFillsByTime")
    if order_json.status != "parsed_untrusted" or fills_json.status != "parsed_untrusted":
        return hold("JSON parsing failed")
    order = parse_order_status_offline(
        request=order_request, response=order_json.payload, account=account,
        coin=coin, oid=oid, direction=direction, requested_size=size,
        submitted_at_ms=submitted_at_ms,
    )
    fills = parse_fills_by_time_offline(
        request=fills_request, response=fills_json.payload, account=account,
        start_ms=start_ms, end_ms=end_ms,
    )
    cross = inspect_order_fill_consistency_offline(
        order_review=order, fills_review=fills, oid=oid, coin=coin,
        direction=direction, size=size, submitted_at_ms=submitted_at_ms,
        start_ms=start_ms, end_ms=end_ms,
    )
    if cross.status != "review_only":
        return hold("order/fill evidence inconsistent or incomplete")
    impact = inspect_account_order_impact_offline(
        target_oid=oid, target_coin=coin, order_status="filled",
        requested_size=size, fills=fills.records,
        open_orders_known_empty=open_orders_known_empty,
        position_snapshot_verified=position_snapshot_verified,
    )
    if impact.status != "review_only":
        return hold("account-level state ambiguous")
    return PipelineReview(
        "review_only",
        "synthetic pipeline passes structural checks only; no provenance, "
        "retention proof, ownership release or trading permission",
    )
