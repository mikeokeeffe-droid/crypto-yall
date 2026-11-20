"""Disposable PostgreSQL bridge for existing bot ENTRY decisions, offline CI ONLY.

This is not an executor integration, order dispatch or production adapter.
No exchange SDK, signer, network client or service role is imported. Only
restricted bot PostgreSQL logins in localhost/safety_test can write an intent.
Original bots and production database are never touched.
"""
from dataclasses import dataclass
from decimal import Decimal
import os
import uuid

from offline_original_bot_intent_adapter import project_original_entry


@dataclass(frozen=True)
class OfflineBridgeDecision:
    state: str = "hold"
    intent_id: str | None = None
    fence: int | None = None
    submit_authorized: bool = False


def record_offline_original_entry(*, connection_factory, verified_bot,
                                  trade, rounded_size, pinned_environment,
                                  pinned_account, pinned_dex=""):
    """Convert an original bot decision to a durable CI-only SQL intent.

    Database session_user, not the trade payload, enforces bot identity.
    Every failure stays HOLD. The result never authorizes exchange calls.
    This SQL schema deliberately has no precommitted CLOID or dispatch path.
    """
    held = OfflineBridgeDecision()
    if (os.environ.get("ISOLATED_POSTGRES_CI") != "1"
            or os.environ.get("PGDATABASE") != "safety_test"
            or os.environ.get("PGHOST") not in ("localhost", "127.0.0.1")
            or not callable(connection_factory)):
        return held
    projected = project_original_entry(
        verified_bot=verified_bot, trade=trade, rounded_size=rounded_size,
        pinned_environment=pinned_environment, pinned_account=pinned_account,
        pinned_dex=pinned_dex,
    )
    if projected is None or projected.submit_authorized:
        return held

    try:
        with connection_factory() as conn:
            if conn.info.host not in ("localhost", "127.0.0.1", "::1"):
                return held
            identity = conn.execute(
                "select current_database(),session_user,current_user"
            ).fetchone()
            if identity != (
                "safety_test", "entry_login_" + projected.bot,
                "entry_login_" + projected.bot,
            ):
                return held
            token = uuid.uuid4()
            row = conn.execute(
                "select recorded,intent_id,fencing "
                "from public.ci_record_pre_submit_intent("
                "%s,%s,%s,%s,%s,%s,%s,%s)",
                (projected.environment, projected.account, projected.dex,
                 projected.coin, projected.bot, token, projected.action,
                 Decimal(projected.size)),
            ).fetchone()
            if (row is None or row[0] is not True
                    or row[1] != token or type(row[2]) is not int
                    or row[2] <= 0):
                return held
            return OfflineBridgeDecision(
                state="reserved_offline_only", intent_id=str(row[1]),
                fence=row[2],
            )
    except Exception:
        # An untrusted or failing DB connection cannot grant an order attempt.
        return held
