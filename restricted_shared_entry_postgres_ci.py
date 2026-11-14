"""Isolated-CI-only real PostgreSQL backend for the entry admission contract.

Uses separate LOGIN identities; the SQL validates session_user, and a single
transaction atomically reserves a coin and persists its unresolved intent.
Never imports a trading executor or submits an exchange order. Not wired into
live bots; never reads production credentials or contacts production Supabase.

The fence_token column is a disposable test-schema extension, not an approved
production migration. No production integration is authorized by this file.
"""
import os
from uuid import UUID

_BOTS = frozenset(("daily", "intraday", "aggressive"))
_ALLOWED = frozenset(("open_long", "open_short", "pyramid_long", "pyramid_short"))
_BLOCKED_LOGINS = frozenset(("postgres", "service_role", "bot_entry_executor_trial"))


class RestrictedPostgresEntryCoordinator:
    def __init__(self, connection_factory, *, expected_bot, expected_login):
        if os.environ.get("PGDATABASE") != "safety_test" or os.environ.get("ISOLATED_POSTGRES_CI") != "1":
            raise RuntimeError("restricted coordinator is not enabled outside isolated CI")
        if not callable(connection_factory):
            raise ValueError("connection factory required")
        if expected_bot not in _BOTS or not isinstance(expected_login, str) or not expected_login or expected_login in _BLOCKED_LOGINS:
            raise ValueError("restricted bot and dedicated LOGIN required")
        self._connect = connection_factory
        self._bot = expected_bot
        self._login = expected_login

    def claim_intent(self, *, bot, coin, action, request_id):
        if bot != self._bot:
            raise PermissionError("cross-bot claims are forbidden")
        if action not in _ALLOWED:
            raise ValueError("invalid increasing action")
        if not isinstance(coin, str) or not coin.isascii() or not coin.isalnum() or coin != coin.upper():
            raise ValueError("invalid coin")
        if str(UUID(request_id)) != request_id:
            raise ValueError("request_id must be a canonical UUID")

        with self._connect() as conn:
            with conn.transaction():
                identity = conn.execute("select session_user,current_user").fetchone()
                if identity != (self._login, self._login):
                    raise PermissionError("dedicated database LOGIN mismatch")
                token = UUID(request_id)
                reserved = conn.execute(
                    "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                    (coin, bot, token, 120)).fetchone()[0]
                if not reserved:
                    return {"status": "blocked"}
                claimed = conn.execute(
                    "select public.claim_bot_entry_intent(%s,%s,%s)",
                    (coin, bot, token)).fetchone()[0]
                if not claimed:
                    # Roll back reservation too: never leave a half-claim.
                    raise RuntimeError("reservation succeeded without durable intent")
                proof = conn.execute(
                    "select bot,coin,token,status,fence_token "
                    "from public.read_bot_entry_claim_proof(%s,%s,%s)",
                    (coin, bot, token)).fetchone()
                if not proof or proof[:4] != (bot, coin, token, "pending"):
                    raise RuntimeError("durable intent evidence mismatch")
                fence = proof[4]
                if type(fence) is not int or fence <= 0:
                    raise RuntimeError("invalid database-issued fencing evidence")
                return {"status": "claimed", "bot": bot, "coin": coin,
                        "action": action, "request_id": request_id,
                        "intent_id": str(proof[2]), "fence_token": fence}
