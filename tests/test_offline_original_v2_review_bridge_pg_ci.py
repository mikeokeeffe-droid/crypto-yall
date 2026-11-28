"""Disposable PostgreSQL integration of non-authorizing original V2 drafts.

A synthetic leverage-bound size draft becomes an immutable REVIEW row, NOT
an order. No real exchange, signer, production DB, release or close action.
"""
import json
import os
import unittest
import uuid

import psycopg

from offline_leverage_bound_entry_draft_ci import (
    OfflineLeverageBoundEntrySink, OfflineLeverageDraft,
)
from offline_original_v2_review_bridge_ci import record_v2_draft_for_offline_review

ACCOUNT = "0x" + "1" * 40
BOTS = ("daily", "intraday", "aggressive")


@unittest.skipUnless(
    os.environ.get("ISOLATED_POSTGRES_CI") == "1"
    and os.environ.get("PGDATABASE") == "safety_test",
    "disposable PostgreSQL safety_test required",
)
class OriginalV2ReviewBridgeTests(unittest.TestCase):
    @staticmethod
    def db(user):
        password = (
            os.environ["PGPASSWORD"] if user == "postgres"
            else "disposable-sender-only" if user == "ci_sender_worker"
            else "disposable-v2-coordinator-" + user.removeprefix("ci_v2_coordinator_") + "-only" if user.startswith("ci_v2_coordinator_")
            else "disposable-" + user.removeprefix("entry_login_") + "-only"
        )
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user=user, password=password,
        )

    def setUp(self):
        with self.db("postgres") as conn:
            conn.execute("truncate public.ci_sender_v2_reviews restart identity")

    @staticmethod
    def draft(bot="daily", action="open_long", size=1.6, leverage=2):
        sink = OfflineLeverageBoundEntrySink(
            bot=bot, trade={"hl_coin": "SOL", "action": action},
            environment="mainnet", account=ACCOUNT,
        )
        sink.update_leverage(leverage, "SOL", True)
        sink.market_open("SOL", action == "open_long", size)
        return sink.last_draft

    def submit(self, bot, draft, request_id=None, factory=None):
        return record_v2_draft_for_offline_review(
            connection_factory=factory or (
                lambda: self.db("ci_v2_coordinator_" + bot)
            ),
            verified_bot=bot, pinned_environment="mainnet",
            pinned_account=ACCOUNT, request_id=request_id or uuid.uuid4(),
            draft=draft,
        )

    def rows(self):
        with self.db("postgres") as conn:
            return conn.execute(
                "select bot,action,requested_size,requested_leverage,"
                "state,cloid from public.ci_sender_v2_reviews"
            ).fetchall()

    def test_three_bots_preserve_leverage_size_and_one_winner(self):
        for bot in BOTS:
            first = self.submit(bot, self.draft(bot))
            if bot == "daily":
                self.assertEqual(first.state, "recorded_review_only")
                self.assertIsInstance(first.token, uuid.UUID)
                self.assertGreater(first.fence, 0)
            else:
                self.assertEqual(first.state, "hold")
            self.assertFalse(first.submit_authorized)
            self.assertFalse(first.leverage_applied)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0:2], ("daily", "open_long"))
        self.assertEqual(str(rows[0][2]), "1.6")
        self.assertEqual(rows[0][3:5], (2, "review_only"))
        self.assertRegex(rows[0][5], r"^0x[0-9a-f]{32}$")
        self.assertEqual(self.submit("daily", self.draft()).state, "hold")
        self.assertEqual(self.rows(), rows)

    def test_spoofed_or_invalid_draft_never_writes(self):
        valid=self.draft()
        payload=json.loads(valid.review_json)
        variations=[
            dict(payload, requested_leverage=6),
            dict(payload, requested_leverage=True),
            dict(payload, requested_leverage=0),
            dict(payload, cross_margin_requested=False),
            dict(payload, action="pyramid_long"),
            dict(payload, bot="aggressive"),
            dict(payload, account=ACCOUNT),
            dict(payload, submit_authorized=True),
            dict(payload, rounded_size="NaN"),
            dict(payload, rounded_size="-1"),
        ]
        for value in variations:
            with self.subTest(value=value):
                altered=OfflineLeverageDraft(
                    state="review_only", review_json=json.dumps(value))
                self.assertEqual(self.submit("daily", altered).state, "hold")
        self.assertEqual(self.submit("daily", OfflineLeverageDraft()).state,
                         "hold")
        unapproved = OfflineLeverageDraft(
            state="review_only", review_json=valid.review_json,
            submit_authorized=True,
        )
        self.assertEqual(self.submit("daily", unapproved).state, "hold")
        self.assertEqual(self.rows(), [])

    def test_mismatched_db_principal_fails_before_sql(self):
        valid=self.draft()
        result=self.submit(
            "daily", valid,
            factory=lambda: self.db("ci_v2_coordinator_intraday"),
        )
        self.assertEqual(result.state, "hold")
        self.assertFalse(result.submit_authorized)
        self.assertEqual(self.rows(), [])

    def test_replayed_request_on_another_coin_remains_hold(self):
        draft=self.draft()
        req=uuid.uuid4()
        first=self.submit("daily", draft, request_id=req)
        self.assertEqual(first.state, "recorded_review_only")
        self.assertEqual(self.submit("daily", draft, request_id=req).state,
                         "hold")
        self.assertEqual(self.submit("intraday", self.draft("intraday")).state,
                         "hold")
        self.assertEqual(len(self.rows()), 1)


if __name__=="__main__":
    unittest.main()
