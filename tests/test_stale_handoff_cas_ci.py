"""Disposable PostgreSQL CAS regression for stale ownership requests.

No real reconciler, exchange calls, order placement, API credentials or
production DB changes. A PostgreSQL *CI administrator* simulates a handoff
with an exact coin/bot/UUID/fence/status conditional update. This deliberately
does NOT grant any routine executor an ownership-change capability.
The simulated CAS cannot authenticate exchange evidence or provide a
production-ready trusted reconciliation boundary.
"""
import concurrent.futures
import os
import unittest
import uuid
from threading import Barrier

import psycopg

from restricted_shared_entry_postgres_ci import RestrictedPostgresEntryCoordinator
from shared_entry_admission import claim_shared_entry


@unittest.skipUnless(
    os.getenv("ISOLATED_POSTGRES_CI") == "1"
    and os.getenv("PGDATABASE") == "safety_test",
    "Only the throwaway GitHub Actions safety_test PostgreSQL database",
)
class StaleHandoffCompareAndSwapTests(unittest.TestCase):
    def admin(self):
        return psycopg.connect(
            host=os.environ["PGHOST"],
            port=int(os.environ["PGPORT"]),
            dbname="safety_test",
            user="postgres",
            password=os.environ["PGPASSWORD"],
            autocommit=True,
        )

    def setUp(self):
        with self.admin() as db:
            db.execute(
                "truncate public.bot_entry_intents, public.bot_entry_reservations"
            )

    def claim(self, bot, coin="SOL"):
        def connect():
            return psycopg.connect(
                host="localhost", port=5432, dbname="safety_test",
                user="entry_login_" + bot,
                password="disposable-" + bot + "-only",
            )

        backend = RestrictedPostgresEntryCoordinator(
            connect, expected_bot=bot, expected_login="entry_login_" + bot
        )
        decision = claim_shared_entry(
            backend, bot=bot, coin=coin, action="open_long",
            request_id=str(uuid.uuid4()),
        )
        self.assertTrue(decision.accepted, decision.reason)
        return decision

    def pretend_exchange_outcome_unknown(self, coin, claim):
        # CI-admin records SYNTHETIC order metadata, never submits an order.
        # The original bot roles still cannot invoke this RPC in CI.
        with self.admin() as db:
            row = db.execute(
                "select bot,token from public.bot_entry_intents "
                "where coin=%s and status='pending'", (coin,),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[1], uuid.UUID(claim.intent_id))
            recorded = db.execute(
                "select public.record_bot_entry_order(%s,%s,%s,%s,%s,%s,%s)",
                (coin, row[0], row[1], "ci-order-" + claim.intent_id,
                 90_000, 2, "uncertain"),
            ).fetchone()[0]
            self.assertTrue(recorded)

    def simulated_cas(self, *, bot, coin, claim, order_id=None,
                      submitted_at_ms=90_000, requested_size=2):
        # CI-superuser simulates PostgreSQL's conditional atomic update ONLY.
        # Exchange evidence is NOT authenticated; there is no trusted service.
        order_id = ("ci-order-" + claim.intent_id
                    if order_id is None else order_id)
        with self.admin() as db:
            changed = db.execute(
                "update public.bot_entry_intents set status='filled' "
                "where coin=%s and bot=%s and token=%s "
                "and fence_token=%s and status='uncertain' "
                "and exchange_order_id=%s and submitted_at_ms=%s "
                "and requested_size=%s returning coin",
                (coin, bot, uuid.UUID(claim.intent_id), claim.fence_token,
                 order_id, submitted_at_ms, requested_size),
            ).fetchone()
            return changed == (coin,)

    def test_exact_generation_only_one_transition(self):
        old = self.claim("daily")
        self.pretend_exchange_outcome_unknown("SOL", old)
        self.assertTrue(self.simulated_cas(bot="daily", coin="SOL", claim=old))
        self.assertFalse(self.simulated_cas(bot="daily", coin="SOL", claim=old))
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select bot,status,fence_token from public.bot_entry_intents "
                "where coin='SOL'"
            ).fetchone(), ("daily", "filled", old.fence_token))

    def test_old_claim_cannot_change_newer_generation_on_same_coin(self):
        old = self.claim("daily")
        self.pretend_exchange_outcome_unknown("SOL", old)
        with self.admin() as db:
            # Pretend a DIFFERENT, fully authorized offline reconcile has
            # completed. This cleanup only happens in a disposable CI DB.
            db.execute("delete from public.bot_entry_intents where coin='SOL'")
            db.execute("delete from public.bot_entry_reservations where coin='SOL'")
        new = self.claim("intraday")
        self.pretend_exchange_outcome_unknown("SOL", new)
        self.assertGreater(new.fence_token, old.fence_token)
        self.assertFalse(self.simulated_cas(bot="daily", coin="SOL", claim=old))
        self.assertFalse(self.simulated_cas(bot="intraday", coin="BTC", claim=new))
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select bot,status,fence_token from public.bot_entry_intents "
                "where coin='SOL'"
            ).fetchone(), ("intraday", "uncertain", new.fence_token))

    def test_wrong_order_metadata_cannot_handoff_correct_fence(self):
        claim = self.claim("daily", "XRP")
        self.pretend_exchange_outcome_unknown("XRP", claim)
        for overrides in (
            {"order_id": "foreign-order"},
            {"submitted_at_ms": 89_999},
            {"submitted_at_ms": 90_001},
            {"requested_size": 1},
            {"requested_size": 3},
        ):
            with self.subTest(overrides=overrides):
                self.assertFalse(self.simulated_cas(
                    bot="daily", coin="XRP", claim=claim, **overrides
                ))
        with self.admin() as db:
            self.assertEqual(
                db.execute(
                    "select status,exchange_order_id,submitted_at_ms,requested_size "
                    "from public.bot_entry_intents where coin='XRP'"
                ).fetchone(),
                ("uncertain", "ci-order-" + claim.intent_id, 90_000, 2),
            )
        self.assertTrue(self.simulated_cas(
            bot="daily", coin="XRP", claim=claim
        ))

    def test_simultaneous_duplicate_workers_get_one_cas_winner(self):
        claim = self.claim("aggressive", "ETH")
        self.pretend_exchange_outcome_unknown("ETH", claim)
        go = Barrier(2)

        def worker(_):
            go.wait(timeout=10)
            return self.simulated_cas(
                bot="aggressive", coin="ETH", claim=claim
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, range(2)))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 1)

    def test_filled_intent_stays_a_fence_after_reservation_expires(self):
        claim = self.claim("daily", "AVAX")
        self.pretend_exchange_outcome_unknown("AVAX", claim)
        self.assertTrue(self.simulated_cas(
            bot="daily", coin="AVAX", claim=claim
        ))
        with self.admin() as db:
            db.execute(
                "update public.bot_entry_reservations "
                "set expires_at=now()-interval '1 second' where coin='AVAX'"
            )
        def connect():
            return psycopg.connect(
                host="localhost", port=5432, dbname="safety_test",
                user="entry_login_intraday",
                password="disposable-intraday-only",
            )
        newcomer = claim_shared_entry(
            RestrictedPostgresEntryCoordinator(
                connect, expected_bot="intraday",
                expected_login="entry_login_intraday"
            ),
            bot="intraday", coin="AVAX",
            action="open_short", request_id=str(uuid.uuid4())
        )
        self.assertFalse(newcomer.accepted)
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select status from public.bot_entry_intents where coin='AVAX'"
            ).fetchone(), ("filled",))

    def test_executor_logins_cannot_run_simulated_handoff_update(self):
        claim = self.claim("daily", "LINK")
        self.pretend_exchange_outcome_unknown("LINK", claim)
        with psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="entry_login_daily",
            password="disposable-daily-only",
        ) as db:
            self.assertFalse(db.execute(
                "select has_table_privilege("
                "current_user,'public.bot_entry_intents','UPDATE')"
            ).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
