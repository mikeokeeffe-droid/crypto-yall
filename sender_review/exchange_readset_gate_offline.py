"""OFFLINE ONLY: require an account-wide exchange read-set evidence MANIFEST.

These are untrusted, synthetic *metadata* records describing data a future
privileged, read-only exchange adapter must fetch independently. Caller claims
of completeness, stable positions, timestamps, identifiers or hashes are NOT
exchange attestations. No network, SDK, database, signing, order generation,
fence release, retry or protective close exists. ALL decisions remain HOLD.

This is a design-time drift/failure detector, never a production verifier.
"""
from dataclasses import dataclass
import re

from sender_review.account_wide_reconciliation_fixture_offline import (
    reconcile_close_fixture_offline,
)

_ACCOUNT = "0x" + "1" * 40
_NETWORK = "testnet"
_BATCH = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_ENDPOINTS = (
    "positions_before", "orders", "fills", "open_orders", "positions_after",
)
_MAX_PAGES = 32
_MAX_RECORDS_PER_PAGE = 500
_MAX_AGE_SECONDS = 10


@dataclass(frozen=True)
class SyntheticExchangePage:
    endpoint: str
    account: str
    network: str
    batch_id: str
    page_number: int
    input_cursor: str | None
    next_cursor: str | None
    record_ids: tuple[str, ...]
    sampled_epoch: int
    claimed_success: bool
    claimed_not_truncated: bool
    claimed_position_digest: str | None = None


@dataclass(frozen=True)
class SyntheticReadSet:
    """A single serial read pass bracketed by position observations."""
    pages: tuple[SyntheticExchangePage, ...]
    outstanding_unknown_order_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReadSetGateResult:
    state: str = "HOLD"
    reason: str = "untrusted exchange read-set"
    fixture_manifest_coherent: bool = False
    fixture_reconciliation_coherent: bool = False
    runtime_identity_authenticated: bool = False
    exchange_transport_authenticated: bool = False
    account_history_verified: bool = False
    position_ownership_verified: bool = False
    read_only_adapter_deployed: bool = False
    request_authorized: bool = False
    close_authorized: bool = False
    retry_authorized: bool = False
    fence_released: bool = False
    signing_enabled: bool = False


def _id(value):
    return type(value) is str and _BATCH.fullmatch(value) is not None


def _check_manifest(readset, *, expected_account, now_epoch):
    if (
        type(readset) is not SyntheticReadSet
        or type(readset.pages) is not tuple
        or not 5 <= len(readset.pages) <= _MAX_PAGES
        or type(expected_account) is not str or expected_account != _ACCOUNT
        or type(now_epoch) is not int
        or type(readset.outstanding_unknown_order_ids) is not tuple
        or not all(_id(x) for x in readset.outstanding_unknown_order_ids)
    ):
        return "missing-or-malformed-manifest"

    grouped = {ep: [] for ep in _ENDPOINTS}
    previous_epoch = None
    last_endpoint_index = -1
    seen_batch = None
    for page in readset.pages:
        if type(page) is not SyntheticExchangePage:
            return "invalid-page"
        if (
            page.endpoint not in grouped
            or page.account != _ACCOUNT or page.network != _NETWORK
            or not _id(page.batch_id)
        ):
            return "wrong-source-scope-or-batch"
        if seen_batch is None:
            seen_batch = page.batch_id
        elif page.batch_id != seen_batch:
            return "mixed-read-batch"
        if (
            type(page.page_number) is not int or page.page_number < 0
            or type(page.record_ids) is not tuple
            or len(page.record_ids) > _MAX_RECORDS_PER_PAGE
            or not all(_id(x) for x in page.record_ids)
            or page.claimed_success is not True
            or page.claimed_not_truncated is not True
        ):
            return "failed-truncated-or-invalid-page"
        if (
            type(page.sampled_epoch) is not int
            or not 0 <= now_epoch - page.sampled_epoch <= _MAX_AGE_SECONDS
            or (previous_epoch is not None and
                page.sampled_epoch < previous_epoch)
        ):
            return "stale-future-or-nonmonotonic-samples"
        previous_epoch = page.sampled_epoch
        endpoint_index = _ENDPOINTS.index(page.endpoint)
        if endpoint_index < last_endpoint_index:
            return "out-of-sequence-read"
        last_endpoint_index = endpoint_index
        if (
            (page.input_cursor is not None and
             not _id(page.input_cursor))
            or (page.next_cursor is not None and
                not _id(page.next_cursor))
        ):
            return "malformed-cursor"
        if page.endpoint in ("positions_before", "positions_after"):
            if (
                page.page_number != 0 or page.input_cursor is not None
                or page.next_cursor is not None
                or type(page.claimed_position_digest) is not str
                or _DIGEST.fullmatch(page.claimed_position_digest) is None
            ):
                return "malformed-position-bookend"
        elif page.claimed_position_digest is not None:
            return "unexpected-bookend-digest"
        grouped[page.endpoint].append(page)

    for endpoint in _ENDPOINTS:
        pages = grouped[endpoint]
        if not pages:
            return "missing-required-endpoint"
        if endpoint.startswith("positions_") and len(pages) != 1:
            return "duplicate-position-bookend"
        seen_records, seen_cursors = set(), set()
        for index, page in enumerate(pages):
            expected_input = None if index == 0 else pages[index - 1].next_cursor
            if page.page_number != index or page.input_cursor != expected_input:
                return "cursor-gap-or-page-reordering"
            if index < len(pages) - 1 and page.next_cursor is None:
                return "missing-next-cursor"
            if index == len(pages) - 1 and page.next_cursor is not None:
                return "unterminated-pagination"
            if page.input_cursor is not None:
                if page.input_cursor in seen_cursors:
                    return "cursor-replay-or-cycle"
                seen_cursors.add(page.input_cursor)
            for record_id in page.record_ids:
                if record_id in seen_records:
                    return "duplicate-record-in-endpoint"
                seen_records.add(record_id)
        if len(pages) > 1 and pages[-1].next_cursor is not None:
            return "unterminated-pagination"

    if (grouped["positions_before"][0].claimed_position_digest !=
            grouped["positions_after"][0].claimed_position_digest):
        return "changed-position-bookends"
    if readset.outstanding_unknown_order_ids:
        return "unknown-ack-still-unresolved"
    return None


def inspect_exchange_readset_fixture_offline(
    *, readset, expected_account, now_epoch,
):
    error = _check_manifest(
        readset, expected_account=expected_account, now_epoch=now_epoch
    )
    if error is not None:
        return ReadSetGateResult(reason=error)
    return ReadSetGateResult(
        reason="coherent-metadata-fixture-only; no verified exchange origin",
        fixture_manifest_coherent=True,
    )


def inspect_close_reconciliation_with_readset_offline(
    *, body, fixture_bot, history, expected_account,
    expected_fence, now_epoch, readset,
):
    """Compose two untrusted fixture checks; ALWAYS refuse execution."""
    manifest = inspect_exchange_readset_fixture_offline(
        readset=readset,
        expected_account=expected_account,
        now_epoch=now_epoch,
    )
    if not manifest.fixture_manifest_coherent:
        return manifest
    review = reconcile_close_fixture_offline(
        body=body, fixture_bot=fixture_bot,
        history=history, expected_account=expected_account,
        expected_fence=expected_fence, now_epoch=now_epoch,
    )
    if not review.fixture_consistent:
        return ReadSetGateResult(
            reason="account-wide-fixture-mismatch: " + review.reason,
            fixture_manifest_coherent=True,
        )
    return ReadSetGateResult(
        reason="two synthetic checks agree; still no real exchange provenance",
        fixture_manifest_coherent=True,
        fixture_reconciliation_coherent=True,
    )
