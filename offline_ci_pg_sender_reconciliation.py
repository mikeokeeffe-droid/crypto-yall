"""Synthetic reconciliation review of immutable sender journal and fake fills.

READ-ONLY disposable PostgreSQL, no Hyperliquid SDK/HTTP, signer, account
ownership handoff or order/close authority. A positive structural match is
still HOLD pending independently authenticated exchange evidence.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os
import re
import uuid

_ACCOUNT = re.compile(r"0x[0-9a-f]{40}\Z", re.ASCII)
_CLOID = re.compile(r"0x[0-9a-f]{32}\Z", re.ASCII)


@dataclass(frozen=True)
class OfflineSenderEvidenceReview:
    state: str
    reason: str
    submit_authorized: bool = False
    ownership_verified: bool = False


def review_sender_fake_evidence(*, reviewer_connection_factory, token, fence,
                                evidence):
    """Review one exact immutable intent and attempt against supplied fakes.

    Fake evidence must explicitly declare its origin; never trust an
    authenticated flag or infer that a same-direction position proves ownership.
    No SQL UPDATE, INSERT, DELETE or function call occurs in this module.
    """
    def hold(reason):
        return OfflineSenderEvidenceReview("hold", reason)

    if (os.environ.get("ISOLATED_POSTGRES_CI") != "1"
            or os.environ.get("PGDATABASE") != "safety_test"
            or os.environ.get("PGHOST") not in ("localhost", "127.0.0.1")
            or not callable(reviewer_connection_factory)
            or type(token) is not uuid.UUID
            or type(fence) is not int or fence <= 0
            or type(evidence) is not dict):
        return hold("untrusted review context")

    try:
        with reviewer_connection_factory() as conn:
            if conn.info.host not in ("localhost", "127.0.0.1", "::1"):
                return hold("nonlocal database connection")
            identity = conn.execute(
                "select current_database(),session_user,current_user"
            ).fetchone()
            if identity != ("safety_test","ci_sender_reviewer","ci_sender_reviewer"):
                return hold("wrong database reviewer identity")
            row = conn.execute(
                "select i.token,i.fence_token,i.environment,i.effective_account,"
                "i.dex,i.coin,i.bot,i.action,i.requested_size,i.cloid,i.state,"
                "a.intent_token,a.fence_token,a.cloid,a.state "
                "from public.ci_sender_intents i "
                "left join public.ci_sender_attempts a on a.intent_token=i.token "
                "where i.token=%s and i.fence_token=%s",
                (token, fence),
            ).fetchone()
    except Exception:
        return hold("review database unavailable or ambiguous")

    if row is None or row[0] != token or row[1] != fence:
        return hold("missing or stale journal identity")
    (_, _, env, account, dex, coin, bot, action, size, cloid, state,
     attempt_token, attempt_fence, attempt_cloid, attempt_state) = row
    if (env not in ("mainnet", "testnet")
            or type(account) is not str or not _ACCOUNT.fullmatch(account)
            or dex != "" or type(coin) is not str or not coin.isascii()
            or not coin.isalnum() or coin != coin.upper()
            or bot not in ("daily", "intraday", "aggressive")
            or action not in ("open_long", "open_short")
            or type(cloid) is not str or not _CLOID.fullmatch(cloid)
            or state != "dispatch_unknown"
            or (attempt_token,attempt_fence,attempt_cloid,attempt_state) !=
               (token,fence,cloid,"dispatch_unknown")):
        return hold("journal identity incomplete or not durably dispatched")

    required = {"origin", "account", "environment", "coin", "side", "cloid",
                "order_id", "status", "requested_size", "fills",
                "fills_complete", "position_provenance"}
    if set(evidence) != required or evidence["origin"] != "fixture":
        return hold("evidence fields or synthetic provenance invalid")
    if evidence["position_provenance"] != "unverified":
        return hold("fake account position cannot prove ownership")
    side = "long" if action == "open_long" else "short"
    if (evidence["account"] != account or evidence["environment"] != env
            or evidence["coin"] != coin or evidence["side"] != side
            or evidence["cloid"] != cloid or type(evidence["order_id"]) is not int
            or evidence["order_id"] <= 0
            or evidence["status"] != "filled"
            or evidence["fills_complete"] is not True
            or type(evidence["fills"]) is not list or not evidence["fills"]):
        return hold("synthetic order identity or coverage mismatch")
    def decimal_amount(raw):
        if type(raw) is not str or not raw or raw.strip() != raw:
            return None
        try:
            value = Decimal(raw)
        except (InvalidOperation, ValueError):
            return None
        return value if value.is_finite() and value > 0 else None

    requested = decimal_amount(str(size))
    if requested is None or decimal_amount(evidence["requested_size"]) != requested:
        return hold("requested quantity mismatch")
    seen = set()
    total = Decimal(0)
    for fill in evidence["fills"]:
        if type(fill) is not dict or set(fill) != {
            "fill_id", "order_id", "coin", "side", "size"
        }:
            return hold("incomplete or unexpected fake fill")
        fid = fill["fill_id"]
        qty = decimal_amount(fill["size"])
        if (type(fid) is not str or not fid or fid in seen
                or type(fill["order_id"]) is not int
                or fill["order_id"] != evidence["order_id"]
                or fill["coin"] != coin or fill["side"] != side
                or qty is None):
            return hold("duplicate, foreign or invalid fake fill")
        seen.add(fid)
        total += qty
    if total != requested:
        return hold("missing, partial or oversized synthetic fill")
    return hold("synthetic consistency only; exchange origin and ownership unverified")
