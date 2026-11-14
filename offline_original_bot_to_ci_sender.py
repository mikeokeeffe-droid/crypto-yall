"""Offline-only bridge from original bot ENTRY decisions to CI sender intents.

This module never imports original executors or any exchange SDK. It can only
reserve entries inside disposable localhost/safety_test PostgreSQL. Bot,
account and environment are supplied by the isolated test harness and checked
against the database session login; trade data cannot supply identity. Neither
reservation nor this return value permits a live order or position ownership.
"""
from dataclasses import dataclass
from decimal import Decimal
import os
import uuid

from offline_original_bot_intent_adapter import project_original_entry


@dataclass(frozen=True)
class OfflineCiSenderAdmission:
    state: str = "hold"
    token: uuid.UUID | None = None
    fence: int | None = None
    submit_authorized: bool = False


def admit_original_entry_to_ci_sender(*, connection_factory, verified_bot,
                                      trade, rounded_size, pinned_environment,
                                      pinned_account, request_id):
    """Record a synthetic original-bot new-entry decision in CI-only journal."""
    hold = OfflineCiSenderAdmission()
    if (os.environ.get("ISOLATED_POSTGRES_CI") != "1"
            or os.environ.get("PGDATABASE") != "safety_test"
            or os.environ.get("PGHOST") not in ("localhost", "127.0.0.1")
            or not callable(connection_factory)
            or type(request_id) is not uuid.UUID):
        return hold

    intent = project_original_entry(
        verified_bot=verified_bot,
        trade=trade,
        rounded_size=rounded_size,
        pinned_environment=pinned_environment,
        pinned_account=pinned_account,
    )
    if intent is None or intent.submit_authorized:
        return hold

    try:
        with connection_factory() as conn:
            if conn.info.host not in ("localhost", "127.0.0.1", "::1"):
                return hold
            identity = conn.execute(
                "select current_database(),session_user,current_user"
            ).fetchone()
            if identity != (
                "safety_test", "entry_login_" + intent.bot,
                "entry_login_" + intent.bot,
            ):
                return hold
            row = conn.execute(
                "select accepted,intent_id,fencing "
                "from public.ci_sender_reserve("
                "%s,%s,%s,%s,%s,%s,%s,%s)",
                (intent.environment, intent.account, intent.dex,
                 intent.coin, intent.bot, intent.action,
                 Decimal(intent.size), request_id),
            ).fetchone()
            if (row is None or row[0] is not True
                    or type(row[1]) is not uuid.UUID
                    or type(row[2]) is not int or row[2] <= 0):
                return hold
            saved = (row[1], row[2])
        # Return only after the DB context commits. No fake side effect here.
        return OfflineCiSenderAdmission("reserved_offline_only", *saved)
    except Exception:
        # An ambiguous commit result is HOLD. Never reissue this request
        # automatically or mark a trade sent from here.
        return hold
