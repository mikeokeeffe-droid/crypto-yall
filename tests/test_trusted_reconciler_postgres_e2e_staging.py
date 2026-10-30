"""Disposable-PostgreSQL reconciliation checks using synthetic identities."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import os
import secrets
from threading import Event, Lock
import unittest
import uuid

import psycopg
from psycopg import sql

from staging_executor_gateway_contract import BOTS
from trusted_reconciler_dispatch_staging import dispatch_staging_reconciliation
from trusted_reconciler_postgres_transport_staging import restricted_reconciler_rpc


ADDRESS = "0x" + "b" * 40
BOT_ORDER = ("aggressive", "intraday", "daily")
KEYS = {
    bot: f"postgres-synthetic-{bot}-reconciler-key-32-bytes".encode()
    for bot in BOTS
}


def signed_token(bot):
    def encode(value):
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        ).rstrip(b"=").decode()

    header = encode({"alg": "HS256", "typ": "JWT"})
    claims = encode({
        "aud": "postgres-synthetic-audience",
        "exp": 200,
        "iat": 90,
        "iss": "postgres-synthetic-issuer",
        "nbf": 90,
        "scope": "reconciler:position-write",
        "sub": "reconciler:" + bot,
    })
    message = header + "." + claims
    signature = hmac.new(KEYS[bot], message.encode(), hashlib.sha256).digest()
    return message + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()


class FakeHyperliquid:
    def __init__(self, *, coin, order_id, status, fills=(), position_size=0,
                 status_error=False):
        self.coin = coin
        self.order_id = order_id
        self.status = status
        self.fills = list(fills)
        self.position_size = position_size
        self.status_error = status_error
        self.order_submissions = 0
        self.open_orders_sequence = []

    def order_status(self, address, order_id):
        if self.status_error:
            raise TimeoutError("synthetic exchange timeout")
        return {"status": "order", "order": {
            "order": {"coin": self.coin, "oid": self.order_id},
            "status": self.status,
        }}

    def user_state(self, address):
        positions = [] if self.position_size == 0 else [{
            "position": {"coin": self.coin, "szi": str(self.position_size)}
        }]
        return {"assetPositions": positions}

    def open_orders(self, address):
        if self.open_orders_sequence:
            return self.open_orders_sequence.pop(0)
        return []

    def user_fills(self, address):
        return list(self.fills)

    def user_fills_by_time(self, address, start_ms, end_ms):
        return [
            item for item in self.fills
            if start_ms <= item["time"] <= end_ms
        ]


@unittest.skipUnless(
    os.getenv("ISOLATED_POSTGRES_CI") == "1",
    "only run on disposable PostgreSQL CI",
)
class ReconcilerPostgresEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.login = "reconciler_e2e_" + uuid.uuid4().hex[:8]
        cls.password = secrets.token_urlsafe(32)
        cls.admin = psycopg.connect(
            host=os.getenv("PGHOST", "localhost"),
            port=int(os.getenv("PGPORT", "5432")),
            dbname=os.getenv("PGDATABASE", "safety_test"),
            user=os.getenv("PGUSER", "postgres"),
            password=os.getenv("PGPASSWORD", "postgres"),
            autocommit=True,
        )
        cls.admin.execute(
            sql.SQL("create role {} login password {}").format(
                sql.Identifier(cls.login), sql.Literal(cls.password),
            )
        )
        cls.admin.execute(
            sql.SQL("grant bot_reconciler to {}").format(
                sql.Identifier(cls.login),
            )
        )

        def connect_reconciler():
            return psycopg.connect(
                host=os.getenv("PGHOST", "localhost"),
                port=int(os.getenv("PGPORT", "5432")),
                dbname=os.getenv("PGDATABASE", "safety_test"),
                user=cls.login,
                password=cls.password,
            )

        cls.rpc = staticmethod(
            restricted_reconciler_rpc(
                connect_reconciler,
                expected_login=cls.login,
            )
        )

    @classmethod
    def tearDownClass(cls):
        cls.admin.execute(
            sql.SQL("revoke bot_reconciler from {}").format(
                sql.Identifier(cls.login),
            )
        )
        cls.admin.execute(
            sql.SQL("drop role if exists {}").format(sql.Identifier(cls.login))
        )
        cls.admin.close()

    def setUp(self):
        self.admin.execute(
            "truncate public.bot_position_owners, public.bot_entry_intents, "
            "public.bot_entry_reservations"
        )

    def create_submitted_intent(self, bot, coin, order_id, *, status="submitted"):
        token = str(uuid.uuid4())
        self.assertTrue(self.admin.execute(
            "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
            (coin, bot, token, 120),
        ).fetchone()[0])
        self.assertTrue(self.admin.execute(
            "select public.claim_bot_entry_intent(%s,%s,%s)",
            (coin, bot, token),
        ).fetchone()[0])
        self.assertTrue(self.admin.execute(
            "select public.record_bot_entry_order(%s,%s,%s,%s,%s,%s,%s)",
            (coin, bot, token, order_id, 99_000, 2, status),
        ).fetchone()[0])
        return token

    def reconcile(self, exchange, *, bot, coin, token, reconciler_rpc=None):
        return dispatch_staging_reconciliation(
            {
                "token": signed_token(bot),
                "operation": "reconcile_entry",
                "args": {"coin": coin, "bot": bot, "token": token},
            },
            info=exchange,
            address=ADDRESS,
            reconciler_rpc=self.rpc if reconciler_rpc is None else reconciler_rpc,
            signing_keys=KEYS,
            issuer="postgres-synthetic-issuer",
            audience="postgres-synthetic-audience",
            now=100,
            clock=lambda: 100,
        )

    def reconcile_owner_release(self, exchange, *, bot, coin, token):
        return dispatch_staging_reconciliation(
            {
                "token": signed_token(bot),
                "operation": "reconcile_release",
                "args": {"coin": coin, "bot": bot, "token": token},
            },
            info=exchange,
            address=ADDRESS,
            reconciler_rpc=self.rpc,
            signing_keys=KEYS,
            issuer="postgres-synthetic-issuer",
            audience="postgres-synthetic-audience",
            now=100,
            clock=lambda: 100,
        )

    def test_three_bots_handoff_final_full_or_partial_fills_idempotently(self):
        scenarios = (
            ("aggressive", "SOL", "filled", 2),
            ("intraday", "ETH", "canceled", 0.5),
            ("daily", "AVAX", "filled", 1.25),
        )
        for bot, coin, status, size in scenarios:
            with self.subTest(bot=bot):
                order_id = str(100 + BOT_ORDER.index(bot))
                token = self.create_submitted_intent(bot, coin, order_id)
                exchange = FakeHyperliquid(
                    coin=coin,
                    order_id=order_id,
                    status=status,
                    fills=[{
                        "coin": coin, "oid": order_id, "sz": str(size),
                        "time": 99_100, "tid": BOT_ORDER.index(bot) + 1,
                    }],
                    position_size=size,
                )
                self.assertTrue(self.reconcile(
                    exchange, bot=bot, coin=coin, token=token
                ).confirmed)
                self.assertTrue(self.reconcile(
                    exchange, bot=bot, coin=coin, token=token
                ).confirmed)
                self.assertEqual(exchange.order_submissions, 0)
                self.assertEqual(self.admin.execute(
                    "select count(*) from public.bot_position_owners "
                    "where coin=%s and bot=%s and token=%s",
                    (coin, bot, token),
                ).fetchone()[0], 1)
                self.assertEqual(self.admin.execute(
                    "select status from public.bot_entry_intents where coin=%s",
                    (coin,),
                ).fetchone()[0], "filled")

    def test_canceled_and_rejected_zero_fill_orders_release_only_after_evidence(self):
        for bot, status, coin in (
            ("aggressive", "canceled", "ATOM"),
            ("intraday", "rejected", "SOL"),
            ("daily", "expired", "AVAX"),
        ):
            with self.subTest(bot=bot):
                order_id = str(200 + BOT_ORDER.index(bot))
                token = self.create_submitted_intent(bot, coin, order_id)
                self.admin.execute(
                    "update public.bot_entry_reservations "
                    "set expires_at=now()-interval '1 hour' where coin=%s",
                    (coin,),
                )
                exchange = FakeHyperliquid(
                    coin=coin, order_id=order_id, status=status,
                )
                result = self.reconcile(
                    exchange, bot=bot, coin=coin, token=token,
                )
                self.assertTrue(result.confirmed, result.reason)
                self.assertIsNone(self.admin.execute(
                    "select 1 from public.bot_entry_intents where coin=%s",
                    (coin,),
                ).fetchone())
                self.assertIsNone(self.admin.execute(
                    "select 1 from public.bot_entry_reservations where coin=%s",
                    (coin,),
                ).fetchone())
                self.assertEqual(exchange.order_submissions, 0)

    def test_owner_release_retry_after_changed_evidence_for_every_bot(self):
        for bot in BOT_ORDER:
            with self.subTest(bot=bot):
                coin = {"aggressive": "DOT", "intraday": "LINK", "daily": "UNI"}[bot]
                order_id = str(500 + BOT_ORDER.index(bot))
                token = self.create_submitted_intent(bot, coin, order_id)
                exchange = FakeHyperliquid(
                    coin=coin,
                    order_id=order_id,
                    status="filled",
                    fills=[{
                        "coin": coin, "oid": order_id, "sz": "1",
                        "time": 99_100, "tid": 20 + BOT_ORDER.index(bot),
                    }],
                    position_size=1,
                )
                self.assertTrue(self.reconcile(
                    exchange, bot=bot, coin=coin, token=token,
                ).confirmed)
                exchange.position_size = 0
                exchange.open_orders_sequence = [
                    [],
                    [{"coin": coin, "oid": "unrelated-open-order"}],
                ]
                self.assertFalse(self.reconcile_owner_release(
                    exchange, bot=bot, coin=coin, token=token,
                ).confirmed)
                self.assertEqual(self.admin.execute(
                    "select state from public.bot_position_owners where coin=%s",
                    (coin,),
                ).fetchone()[0], "closed")

                exchange.open_orders_sequence = [[], []]
                self.assertTrue(self.reconcile_owner_release(
                    exchange, bot=bot, coin=coin, token=token,
                ).confirmed)
                self.assertIsNone(self.admin.execute(
                    "select 1 from public.bot_position_owners where coin=%s",
                    (coin,),
                ).fetchone())
                self.assertIsNone(self.admin.execute(
                    "select 1 from public.bot_entry_intents where coin=%s",
                    (coin,),
                ).fetchone())
                self.assertIsNone(self.admin.execute(
                    "select 1 from public.bot_entry_reservations where coin=%s",
                    (coin,),
                ).fetchone())

    def test_timeout_unknown_order_and_expired_ttl_keep_cross_bot_fence(self):
        token = self.create_submitted_intent(
            "daily", "BTC", "300", status="uncertain",
        )
        self.admin.execute(
            "update public.bot_entry_reservations "
            "set expires_at=now()-interval '1 hour' where coin='BTC'"
        )
        exchange = FakeHyperliquid(
            coin="BTC", order_id="300", status="unknown", status_error=True,
        )
        for _ in range(2):
            self.assertFalse(self.reconcile(
                exchange, bot="daily", coin="BTC", token=token,
            ).confirmed)
        self.assertFalse(self.admin.execute(
            "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
            ("BTC", "aggressive", str(uuid.uuid4()), 120),
        ).fetchone()[0])
        self.assertEqual(self.admin.execute(
            "select status from public.bot_entry_intents where coin='BTC'"
        ).fetchone()[0], "uncertain")
        self.assertEqual(self.admin.execute(
            "select count(*) from public.bot_position_owners where coin='BTC'"
        ).fetchone()[0], 0)

        # A failed evidence read must leave the durable intent recoverable.
        exchange.status_error = False
        exchange.status = "canceled"
        recovered = self.reconcile(
            exchange, bot="daily", coin="BTC", token=token,
        )
        self.assertTrue(recovered.confirmed, recovered.reason)
        self.assertIsNone(self.admin.execute(
            "select 1 from public.bot_entry_intents where coin='BTC'"
        ).fetchone())
        self.assertIsNone(self.admin.execute(
            "select 1 from public.bot_entry_reservations where coin='BTC'"
        ).fetchone())

    def test_concurrent_reconcilers_serialize_release_handoff_and_fence(self):
        def gated_rpc(target_function, ready, proceed):
            arrivals = 0
            arrivals_lock = Lock()

            def rpc(function, params):
                nonlocal arrivals
                if function == target_function:
                    with arrivals_lock:
                        arrivals += 1
                        if arrivals == 2:
                            ready.set()
                    if not proceed.wait(timeout=10):
                        raise TimeoutError("concurrent SQL transition gate timed out")
                return self.rpc(function, params)

            return rpc

        # Both independent attempts verify the same no-fill intent. Keep them
        # just before the SQL release, where a third bot must still be fenced.
        release_token = self.create_submitted_intent(
            "daily", "SOL", "601",
        )
        self.admin.execute(
            "update public.bot_entry_reservations "
            "set expires_at=now()-interval '1 hour' where coin='SOL'"
        )
        release_exchange = FakeHyperliquid(
            coin="SOL", order_id="601", status="canceled",
        )
        release_ready, release_proceed = Event(), Event()
        release_rpc = gated_rpc(
            "release_resolved_bot_entry_intent",
            release_ready,
            release_proceed,
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [
                pool.submit(
                    self.reconcile,
                    release_exchange,
                    bot="daily",
                    coin="SOL",
                    token=release_token,
                    reconciler_rpc=release_rpc,
                )
                for _ in range(2)
            ]
            self.assertTrue(
                release_ready.wait(timeout=10),
                "both reconcilers did not reach the SQL release",
            )
            self.assertFalse(self.admin.execute(
                "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                ("SOL", "aggressive", str(uuid.uuid4()), 120),
            ).fetchone()[0])
            release_proceed.set()
            release_results = [attempt.result(timeout=15) for attempt in attempts]

        self.assertEqual(sum(result.confirmed for result in release_results), 1)
        self.assertIsNone(self.admin.execute(
            "select 1 from public.bot_entry_intents where coin='SOL'"
        ).fetchone())
        self.assertIsNone(self.admin.execute(
            "select 1 from public.bot_entry_reservations where coin='SOL'"
        ).fetchone())
        self.assertEqual(self.admin.execute(
            "select count(*) from public.bot_position_owners where coin='SOL'"
        ).fetchone()[0], 0)

        # Two verified handoffs for one filled intent are idempotent: the
        # owner row remains unique and continues to block every other bot.
        owner_token = self.create_submitted_intent(
            "intraday", "ETH", "602",
        )
        owner_exchange = FakeHyperliquid(
            coin="ETH",
            order_id="602",
            status="filled",
            fills=[{
                "coin": "ETH", "oid": "602", "sz": "1",
                "time": 99_100, "tid": 602,
            }],
            position_size=1,
        )
        owner_ready, owner_proceed = Event(), Event()
        owner_rpc = gated_rpc(
            "record_bot_position_owner",
            owner_ready,
            owner_proceed,
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [
                pool.submit(
                    self.reconcile,
                    owner_exchange,
                    bot="intraday",
                    coin="ETH",
                    token=owner_token,
                    reconciler_rpc=owner_rpc,
                )
                for _ in range(2)
            ]
            self.assertTrue(
                owner_ready.wait(timeout=10),
                "both reconcilers did not reach the SQL ownership handoff",
            )
            self.assertFalse(self.admin.execute(
                "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                ("ETH", "daily", str(uuid.uuid4()), 120),
            ).fetchone()[0])
            owner_proceed.set()
            owner_results = [attempt.result(timeout=15) for attempt in attempts]

        self.assertTrue(all(result.confirmed for result in owner_results))
        self.assertEqual(self.admin.execute(
            "select count(*) from public.bot_position_owners "
            "where coin='ETH' and bot='intraday' and token=%s "
            "and exchange_order_id='602' and state='owned'",
            (owner_token,),
        ).fetchone()[0], 1)
        self.assertEqual(self.admin.execute(
            "select status from public.bot_entry_intents where coin='ETH'"
        ).fetchone()[0], "filled")

    def test_failed_release_rolls_back_owner_delete_transaction(self):
        coin = "MATIC"
        token = str(uuid.uuid4())
        self.admin.execute(
            "insert into public.bot_position_owners "
            "(coin, bot, token, exchange_order_id, state) "
            "values (%s, %s, %s, %s, 'closed')",
            (coin, "daily", token, "orphaned-order"),
        )
        with self.assertRaises(psycopg.errors.RaiseException):
            self.rpc("release_closed_bot_position", {
                "p_coin": coin,
                "p_bot": "daily",
                "p_token": token,
                "p_exchange_flat": True,
                "p_no_open_orders": True,
            })

        self.assertEqual(self.admin.execute(
            "select state from public.bot_position_owners "
            "where coin=%s and bot=%s and token=%s",
            (coin, "daily", token),
        ).fetchone()[0], "closed")
        self.assertIsNone(self.admin.execute(
            "select 1 from public.bot_entry_intents where coin=%s",
            (coin,),
        ).fetchone())

    def test_three_bot_reservation_race_and_duplicate_order_identity(self):
        tokens = {bot: str(uuid.uuid4()) for bot in BOT_ORDER}

        def reserve(bot):
            with psycopg.connect(
                host=os.getenv("PGHOST", "localhost"),
                port=int(os.getenv("PGPORT", "5432")),
                dbname=os.getenv("PGDATABASE", "safety_test"),
                user=os.getenv("PGUSER", "postgres"),
                password=os.getenv("PGPASSWORD", "postgres"),
            ) as conn:
                return bot, conn.execute(
                    "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
                    ("DOGE", bot, tokens[bot], 120),
                ).fetchone()[0]

        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(reserve, BOT_ORDER))
        winners = [(bot, tokens[bot]) for bot, acquired in results if acquired]
        self.assertEqual(len(winners), 1, results)
        bot, token = winners[0]
        self.assertTrue(self.admin.execute(
            "select public.claim_bot_entry_intent(%s,%s,%s)",
            ("DOGE", bot, token),
        ).fetchone()[0])
        self.assertTrue(self.admin.execute(
            "select public.record_bot_entry_order(%s,%s,%s,%s,%s,%s,%s)",
            ("DOGE", bot, token, "401", 99_000, 2, "submitted"),
        ).fetchone()[0])
        self.assertFalse(self.admin.execute(
            "select public.record_bot_entry_order(%s,%s,%s,%s,%s,%s,%s)",
            ("DOGE", bot, token, "402", 99_000, 2, "submitted"),
        ).fetchone()[0])
        other_bot = next(candidate for candidate in BOT_ORDER if candidate != bot)
        self.assertFalse(self.admin.execute(
            "select public.try_reserve_bot_entry(%s,%s,%s,%s)",
            ("DOGE", other_bot, str(uuid.uuid4()), 120),
        ).fetchone()[0])

    def test_reconciler_login_cannot_use_executor_rpc_or_direct_table_writes(self):
        with psycopg.connect(
            host=os.getenv("PGHOST", "localhost"),
            port=int(os.getenv("PGPORT", "5432")),
            dbname=os.getenv("PGDATABASE", "safety_test"),
            user=self.login,
            password=self.password,
        ) as conn:
            self.assertEqual(conn.execute(
                "select session_user, current_user",
            ).fetchone(), (self.login, self.login))
            self.assertFalse(conn.execute(
                "select has_function_privilege(current_user, "
                "'public.try_reserve_bot_entry(text,text,uuid,integer)', "
                "'EXECUTE')",
            ).fetchone()[0])
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute(
                        "update public.bot_entry_intents set status=status "
                        "where false"
                    )


if __name__ == "__main__":
    unittest.main()
