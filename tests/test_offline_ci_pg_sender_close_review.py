"""Disposable PostgreSQL end-to-end negative close tests, never real orders."""
import copy
import os
import uuid
import unittest

import psycopg

from offline_ci_pg_sender_close_review import review_sender_close_offline

ACCOUNT = "0x" + "1" * 40


@unittest.skipUnless(
    os.getenv("ISOLATED_POSTGRES_CI") == "1"
    and os.getenv("PGDATABASE") == "safety_test",
    "disposable PostgreSQL only",
)
class SenderCloseReviewTests(unittest.TestCase):
    @staticmethod
    def connect(user, password):
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user=user, password=password,
        )

    @classmethod
    def reviewer(cls):
        return cls.connect("ci_sender_reviewer", "disposable-reviewer-only")

    def setUp(self):
        with psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="postgres", password=os.environ["PGPASSWORD"],
            autocommit=True,
        ) as db:
            db.execute("truncate public.ci_sender_attempts, "
                       "public.ci_sender_intents restart identity")
        with self.connect("entry_login_daily", "disposable-daily-only") as db:
            accepted, self.token, self.fence = db.execute(
                "select accepted,intent_id,fencing from public.ci_sender_reserve("
                "%s,%s,%s,%s,%s,%s,%s,%s)",
                ("mainnet",ACCOUNT,"","SOL","daily","open_long",
                 "0.025",uuid.uuid4()),
            ).fetchone()
        self.assertTrue(accepted)
        with self.connect("ci_sender_worker", "disposable-sender-only") as db:
            marked, self.cloid = db.execute(
                "select marked,stored_cloid "
                "from public.ci_sender_mark_unknown(%s,%s)",
                (self.token,self.fence),
            ).fetchone()
        self.assertTrue(marked)
        self.evidence = dict(
            origin="fixture", account=ACCOUNT, environment="mainnet",
            coin="SOL", side="long", cloid=self.cloid, order_id=701,
            status="filled", requested_size="0.025", fills_complete=True,
            position_provenance="unverified",
            fills=[dict(fill_id="f1",order_id=701,coin="SOL",
                        side="long",size="0.025")],
        )
        self.request = dict(
            bot="daily",account=ACCOUNT,coin="SOL",side="long",
            close_size="0.010",reduce_only=True,snapshot_source="fixture",
        )

    def check(self, **changes):
        args=dict(
            reviewer_connection_factory=self.reviewer,
            token=self.token, fence=self.fence,
            expected_bot="daily", expected_account=ACCOUNT,
            expected_coin="SOL", evidence=self.evidence,
            close_request=self.request,
        )
        args.update(changes)
        return review_sender_close_offline(**args)

    def test_consistent_journal_and_fills_remain_hold(self):
        decision=self.check()
        self.assertEqual(decision.state,"hold")
        self.assertTrue(decision.structurally_consistent)
        self.assertFalse(decision.submit_authorized)
        self.assertFalse(decision.ownership_verified)

    def test_other_bot_account_coin_or_side_never_close(self):
        for field,value in (
            ("bot","intraday"),("account","0x"+"2"*40),
            ("coin","AVAX"),("side","short"),
        ):
            with self.subTest(field=field):
                req=dict(self.request,**{field:value})
                result=self.check(close_request=req)
                self.assertEqual(result.state,"hold")
                self.assertFalse(result.structurally_consistent)

    def test_oversized_or_invalid_close_cannot_pass_structure(self):
        for amount in ("0","0.026","-1","NaN","Infinity","",0.01):
            with self.subTest(amount=amount):
                req=dict(self.request,close_size=amount)
                result=self.check(close_request=req)
                self.assertEqual(result.state,"hold")
                self.assertFalse(result.structurally_consistent)

    def test_disable_reduce_only_or_forge_provenance_holds(self):
        for changes in (
            {"reduce_only":False},
            {"reduce_only":"true"},
            {"snapshot_source":"exchange_verified"},
        ):
            self.assertFalse(
                self.check(close_request=dict(self.request,**changes))
                .structurally_consistent
            )

    def test_partial_foreign_duplicate_and_ambiguous_evidence_holds(self):
        cases=[
            {"fills_complete":False},
            {"fills":[dict(self.evidence["fills"][0],size="0.020")]},
            {"fills":self.evidence["fills"]*2},
            {"cloid":"0x"+"0"*32},
            {"origin":"exchange"},
            {"position_provenance":"verified"},
        ]
        for change in cases:
            with self.subTest(change=str(change)[:60]):
                evidence=copy.deepcopy(self.evidence)
                evidence.update(change)
                decision=self.check(evidence=evidence)
                self.assertEqual(decision.state,"hold")
                self.assertFalse(decision.structurally_consistent)

    def test_stale_token_fence_or_wrong_reviewer_identity_holds(self):
        for change in (
            {"fence":self.fence+1},
            {"token":uuid.uuid4()},
            {"reviewer_connection_factory":lambda:self.connect(
                "entry_login_daily","disposable-daily-only")},
        ):
            result=self.check(**change)
            self.assertEqual(result.state,"hold")
            self.assertFalse(result.structurally_consistent)


if __name__ == "__main__":
    unittest.main()
