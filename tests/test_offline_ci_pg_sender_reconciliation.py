"""Disposable SQL journal + fake evidence review. All results remain HOLD."""
import copy
import os
import unittest
import uuid

import psycopg
from psycopg.errors import InsufficientPrivilege

from offline_ci_pg_sender_reconciliation import review_sender_fake_evidence

ACCOUNT="0x"+"1"*40


@unittest.skipUnless(
    os.environ.get("ISOLATED_POSTGRES_CI")=="1"
    and os.environ.get("PGDATABASE")=="safety_test",
    "requires isolated PostgreSQL safety_test",
)
class SenderFakeReconciliationTests(unittest.TestCase):
    def admin(self):
        return psycopg.connect(
            host="localhost",port=5432,dbname="safety_test",
            user="postgres",password=os.environ["PGPASSWORD"],
            autocommit=True,
        )

    @staticmethod
    def reviewer():
        return psycopg.connect(
            host="localhost",port=5432,dbname="safety_test",
            user="ci_sender_reviewer",password="disposable-reviewer-only",
        )

    def setUp(self):
        with self.admin() as db:
            db.execute(
                "truncate public.ci_sender_attempts, "
                "public.ci_sender_intents restart identity"
            )
        with psycopg.connect(
            host="localhost",port=5432,dbname="safety_test",
            user="entry_login_daily",password="disposable-daily-only",
        ) as db:
            accepted,self.token,self.fence=db.execute(
                "select accepted,intent_id,fencing from "
                "public.ci_sender_reserve(%s,%s,%s,%s,%s,%s,%s,%s)",
                ("mainnet",ACCOUNT,"","SOL","daily","open_long",
                 "0.025",uuid.uuid4()),
            ).fetchone()
        self.assertTrue(accepted)
        with self.admin() as db:
            self.cloid=db.execute(
                "select cloid from public.ci_sender_intents where token=%s",
                (self.token,),
            ).fetchone()[0]
        self.evidence={
            "origin":"fixture", "environment":"mainnet",
            "account":ACCOUNT, "coin":"SOL", "side":"long",
            "cloid":self.cloid, "order_id":901, "status":"filled",
            "requested_size":"0.025", "fills_complete":True,
            "position_provenance":"unverified",
            "fills":[{"fill_id":"f1","order_id":901,"coin":"SOL",
                      "side":"long","size":"0.010"},
                     {"fill_id":"f2","order_id":901,"coin":"SOL",
                      "side":"long","size":"0.015"}],
        }

    def review(self,evidence=None,**overrides):
        args=dict(
            reviewer_connection_factory=self.reviewer,
            token=self.token,fence=self.fence,
            evidence=self.evidence if evidence is None else evidence,
        )
        args.update(overrides)
        return review_sender_fake_evidence(**args)

    def mark(self):
        with psycopg.connect(
            host="localhost",port=5432,dbname="safety_test",
            user="ci_sender_worker",password="disposable-sender-only",
        ) as db:
            return db.execute(
                "select marked from public.ci_sender_mark_unknown(%s,%s)",
                (self.token,self.fence),
            ).fetchone()[0]

    def test_consistent_two_fill_fake_is_still_hold(self):
        self.assertTrue(self.mark())
        result=self.review()
        self.assertEqual(result.state,"hold")
        self.assertIn("ownership unverified",result.reason)
        self.assertFalse(result.submit_authorized)
        self.assertFalse(result.ownership_verified)
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select state from public.ci_sender_intents"
            ).fetchone()[0],"dispatch_unknown")

    def test_unmarked_intent_cannot_be_reconciled(self):
        result=self.review()
        self.assertEqual(result.state,"hold")
        self.assertIn("journal identity",result.reason)
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_sender_attempts"
            ).fetchone()[0],0)

    def test_missing_duplicate_foreign_and_partial_fills_hold(self):
        self.assertTrue(self.mark())
        modifications=[
            {"fills_complete":False},
            {"status":"open"},
            {"cloid":"0x"+"0"*32},
            {"account":"0x"+"2"*40},
            {"position_provenance":"verified"},
            {"origin":"exchange"},
            {"requested_size":"0.050"},
            {"order_id":902},
            {"fills":[]},
            {"fills":[self.evidence["fills"][0]]},
            {"fills":self.evidence["fills"]+[self.evidence["fills"][0]]},
            {"fills":[dict(self.evidence["fills"][0],side="short"),
                      self.evidence["fills"][1]]},
        ]
        for change in modifications:
            with self.subTest(change=change):
                evidence=copy.deepcopy(self.evidence)
                evidence.update(change)
                result=self.review(evidence)
                self.assertEqual(result.state,"hold")
                self.assertFalse(result.submit_authorized)
                self.assertFalse(result.ownership_verified)

    def test_wrong_database_principal_and_stale_fence_hold(self):
        self.assertTrue(self.mark())
        for args in (
            {"fence":self.fence+1},
            {"token":uuid.uuid4()},
            {"reviewer_connection_factory":lambda: psycopg.connect(
                host="localhost",port=5432,dbname="safety_test",
                user="entry_login_daily",password="disposable-daily-only",
            )},
        ):
            with self.subTest(args=list(args)):
                self.assertEqual(self.review(**args).state,"hold")

    def test_reviewer_denied_send_reserve_and_mutation(self):
        self.assertTrue(self.mark())
        with self.reviewer() as db:
            for table in ("public.ci_sender_intents",
                          "public.ci_sender_attempts"):
                with self.subTest(table=table):
                    with self.assertRaises(InsufficientPrivilege):
                        db.execute("delete from "+table)
                    db.rollback()
                    with self.assertRaises(InsufficientPrivilege):
                        db.execute("update "+table+" set state=state")
                    db.rollback()
            with self.assertRaises(InsufficientPrivilege):
                db.execute(
                    "select * from public.ci_sender_mark_unknown(%s,%s)",
                    (self.token,self.fence),
                )
            db.rollback()
            with self.assertRaises(InsufficientPrivilege):
                db.execute(
                    "select * from public.ci_sender_reserve("
                    "%s,%s,%s,%s,%s,%s,%s,%s)",
                    ("mainnet",ACCOUNT,"","AVAX","daily","open_long",
                     "1",uuid.uuid4()),
                )
            db.rollback()
        self.assertEqual(self.review().state,"hold")


if __name__=="__main__":
    unittest.main()
