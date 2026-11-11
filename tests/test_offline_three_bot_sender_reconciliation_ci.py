"""End-to-end, three original bot synthetic entry -> send -> review CI.

Only localhost disposable PostgreSQL, FakeExchange, and synthetic fills.
No import of live executors, Hyperliquid SDK, order APIs or signing credentials.
"""
import concurrent.futures
import copy
import os
import uuid
import unittest

import psycopg

from offline_original_bot_to_ci_sender import admit_original_entry_to_ci_sender
from offline_ci_pg_fake_sender import simulate_postgres_fake_dispatch_once
from offline_ci_pg_sender_reconciliation import review_sender_fake_evidence
from offline_shared_sender_prototype import FakeExchange

ACCOUNT = "0x" + "1" * 40
BOTS = ("daily", "intraday", "aggressive")


@unittest.skipUnless(
    os.getenv("ISOLATED_POSTGRES_CI") == "1"
    and os.getenv("PGDATABASE") == "safety_test",
    "disposable PostgreSQL safety_test only",
)
class ThreeOriginalBotsToReconciliationTests(unittest.TestCase):
    @staticmethod
    def admin():
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="postgres", password=os.environ["PGPASSWORD"],
            autocommit=True,
        )

    @staticmethod
    def bot_connection(bot):
        def make():
            return psycopg.connect(
                host="localhost", port=5432, dbname="safety_test",
                user="entry_login_" + bot,
                password="disposable-" + bot + "-only",
            )
        return make

    @staticmethod
    def sender():
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="ci_sender_worker", password="disposable-sender-only",
        )

    @staticmethod
    def reviewer():
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="ci_sender_reviewer", password="disposable-reviewer-only",
        )

    def setUp(self):
        with self.admin() as db:
            db.execute("truncate public.ci_sender_attempts, "
                       "public.ci_sender_intents restart identity")

    def enter(self, bot, *, coin="SOL", action="open_long", side="long",
              quantity="0.025", connection_bot=None, trade_override=None,
              request_id=None):
        trade = (trade_override if trade_override is not None
                 else {"action": action, "side": side, "hl_coin": coin})
        return admit_original_entry_to_ci_sender(
            connection_factory=self.bot_connection(connection_bot or bot),
            verified_bot=bot,
            trade=trade,
            rounded_size=quantity,
            pinned_environment="mainnet",
            pinned_account=ACCOUNT,
            request_id=request_id or uuid.uuid4(),
        )

    def journal(self):
        with self.admin() as db:
            return db.execute(
                "select i.token,i.fence_token,i.cloid,i.bot,i.coin,i.action,"
                "i.requested_size,i.state,a.intent_token,a.fence_token,a.cloid "
                "from public.ci_sender_intents i "
                "left join public.ci_sender_attempts a on a.intent_token=i.token"
            ).fetchall()

    def fake_evidence(self, cloid, coin="SOL", side="long"):
        return {
            "origin": "fixture", "environment": "mainnet",
            "account": ACCOUNT, "coin": coin, "side": side,
            "cloid": cloid, "order_id": 901, "status": "filled",
            "requested_size": "0.025", "fills_complete": True,
            "position_provenance": "unverified",
            "fills": [{"fill_id": "f1", "order_id": 901, "coin": coin,
                       "side": side, "size": "0.010"},
                      {"fill_id": "f2", "order_id": 901, "coin": coin,
                       "side": side, "size": "0.015"}],
        }

    def test_three_original_bot_decisions_to_one_fake_send_and_hold_review(self):
        actions = [("daily", "open_long", "long"),
                   ("intraday", "open_short", "short"),
                   ("aggressive", "open_long", "long")]

        def contender(item):
            bot, action, side = item
            return self.enter(bot, action=action, side=side)

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            requests = list(pool.map(contender, actions))
        winners = [x for x in requests if x.state == "reserved_offline_only"]
        self.assertEqual(len(winners), 1, requests)
        self.assertTrue(all(not x.submit_authorized for x in requests))
        token, fence = winners[0].token, winners[0].fence
        rows = self.journal()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0][0], rows[0][1]), (token, fence))
        self.assertEqual(rows[0][7], "reserved")
        self.assertRegex(rows[0][2], r"^0x[0-9a-f]{32}$")
        self.assertEqual(str(rows[0][6]), "0.025")

        fake = FakeExchange()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(
                lambda _: simulate_postgres_fake_dispatch_once(
                    sender_connection_factory=self.sender,
                    token=token, fence=fence, fake=fake,
                ), range(8),
            ))
        self.assertEqual(
            sum(r.state == "observed_unverified" for r in results), 1,
            results,
        )
        self.assertEqual(fake.attempts, [(str(token), rows[0][2])])
        self.assertTrue(all(not r.submit_authorized for r in results))

        new_rows = self.journal()
        self.assertEqual(len(new_rows), 1)
        self.assertEqual(new_rows[0][7], "dispatch_unknown")
        self.assertEqual(new_rows[0][8:], (token, fence, rows[0][2]))
        side = "long" if rows[0][5] == "open_long" else "short"
        reviewed = review_sender_fake_evidence(
            reviewer_connection_factory=self.reviewer,
            token=token, fence=fence,
            evidence=self.fake_evidence(rows[0][2], side=side),
        )
        self.assertEqual(reviewed.state, "hold")
        self.assertIn("ownership unverified", reviewed.reason)
        self.assertFalse(reviewed.ownership_verified)
        self.assertFalse(reviewed.submit_authorized)
        self.assertEqual(self.enter("aggressive").state, "hold")
        self.assertEqual(self.journal(), new_rows)

    def test_all_three_bots_can_reconcile_distinct_synthetic_coins(self):
        examples = (
            ("daily", "SOL", "open_long", "long"),
            ("intraday", "AVAX", "open_short", "short"),
            ("aggressive", "LINK", "open_long", "long"),
        )
        fake = FakeExchange()
        for bot, coin, action, side in examples:
            with self.subTest(bot=bot, coin=coin):
                admitted = self.enter(bot, coin=coin,
                                      action=action, side=side)
                self.assertEqual(admitted.state, "reserved_offline_only")
                sent = simulate_postgres_fake_dispatch_once(
                    sender_connection_factory=self.sender,
                    token=admitted.token, fence=admitted.fence,
                    fake=fake,
                )
                self.assertEqual(sent.state, "observed_unverified")
                with self.admin() as db:
                    cloid = db.execute(
                        "select cloid from public.ci_sender_intents "
                        "where token=%s", (admitted.token,),
                    ).fetchone()[0]
                reviewed = review_sender_fake_evidence(
                    reviewer_connection_factory=self.reviewer,
                    token=admitted.token, fence=admitted.fence,
                    evidence=self.fake_evidence(cloid, coin=coin, side=side),
                )
                self.assertEqual(reviewed.state, "hold")
                self.assertFalse(reviewed.ownership_verified)
                self.assertFalse(reviewed.submit_authorized)
        self.assertEqual(len(self.journal()), 3)
        self.assertEqual(len(fake.attempts), 3)

    def test_spoofed_bot_and_unsupported_original_actions_never_send(self):
        self.assertEqual(
            self.enter("daily", connection_bot="intraday").state, "hold"
        )
        self.assertEqual(
            self.enter("daily", action="pyramid_long").state, "hold"
        )
        self.assertEqual(
            self.enter("aggressive", action="close").state, "hold"
        )
        self.assertEqual(
            self.enter("intraday", trade_override={
                "action": "open_long", "side": "long", "hl_coin": "SOL",
                "account": ACCOUNT,
            }).state, "hold"
        )
        self.assertEqual(self.journal(), [])

    def test_replay_and_unknown_fake_ack_preserve_one_intent(self):
        request_id = uuid.uuid4()
        first = self.enter("daily", request_id=request_id)
        self.assertEqual(first.state, "reserved_offline_only")
        self.assertEqual(
            self.enter("daily", request_id=request_id).state, "hold"
        )
        fake = FakeExchange()
        def timeout_after_fake(token, cloid):
            fake.attempts.append((token, cloid))
            raise TimeoutError("fixture acknowledgement lost")
        fake.record_fake_attempt = timeout_after_fake
        result = simulate_postgres_fake_dispatch_once(
            sender_connection_factory=self.sender,
            token=first.token, fence=first.fence, fake=fake,
        )
        self.assertEqual(result.state, "hold")
        self.assertEqual(len(fake.attempts), 1)
        restarted = simulate_postgres_fake_dispatch_once(
            sender_connection_factory=self.sender,
            token=first.token, fence=first.fence, fake=fake,
        )
        self.assertEqual(restarted.state, "hold")
        self.assertEqual(len(fake.attempts), 1)
        rows = self.journal()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][7], "dispatch_unknown")
        self.assertEqual(
            review_sender_fake_evidence(
                reviewer_connection_factory=self.reviewer,
                token=first.token, fence=first.fence,
                evidence=self.fake_evidence(rows[0][2]),
            ).state,
            "hold",
        )


if __name__ == "__main__":
    unittest.main()
