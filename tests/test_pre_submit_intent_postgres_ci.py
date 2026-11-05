"""Isolated PostgreSQL: atomic scoped entry intent without trade permission."""
import concurrent.futures
import os
import unittest
import uuid
import psycopg
from psycopg.errors import InsufficientPrivilege

ADDRESS = "0x" + "1" * 40
OTHER_ADDRESS = "0x" + "2" * 40

@unittest.skipUnless(
    os.getenv("ISOLATED_POSTGRES_CI") == "1" and
    os.getenv("PGDATABASE") == "safety_test",
    "Only disposable GitHub Actions PostgreSQL",
)
class DurableScopedIntentTests(unittest.TestCase):
    def admin(self):
        return psycopg.connect(host="localhost", port=5432, dbname="safety_test",
                               user="postgres", password=os.environ["PGPASSWORD"],
                               autocommit=True)

    def bot(self, name):
        return psycopg.connect(host="localhost", port=5432, dbname="safety_test",
                               user="entry_login_" + name,
                               password="disposable-" + name + "-only")

    def setUp(self):
        with self.admin() as db:
            db.execute("truncate public.ci_scoped_entry_intents, "
                       "public.ci_scoped_entry_claims")

    def record(self, bot="daily", *, account=ADDRESS, environment="mainnet",
               coin="SOL", action="open_long", size="2", token=None):
        with self.bot(bot) as db:
            return db.execute(
                "select recorded,intent_id,fencing "
                "from public.ci_record_pre_submit_intent("
                "%s,%s,%s,%s,%s,%s,%s,%s)",
                (environment,account,"",coin,bot,token or uuid.uuid4(),
                 action,size),
            ).fetchone()

    def test_claim_and_exact_intent_commit_together(self):
        token = uuid.uuid4()
        result = self.record(token=token,action="open_short",size="0.75")
        self.assertEqual(result[0:2],(True,token))
        self.assertGreater(result[2],0)
        with self.admin() as db:
            row = db.execute(
                "select c.bot,c.token,c.fence_token,i.action,i.requested_size,"
                "i.environment,i.effective_account,i.status "
                "from public.ci_scoped_entry_claims c "
                "join public.ci_scoped_entry_intents i "
                "on i.intent_token=c.token where c.coin='SOL'",
            ).fetchone()
        self.assertEqual((row[0],row[1],row[2],row[3],row[5],row[6],row[7]),
                         ("daily",token,result[2],"open_short","mainnet",ADDRESS,"pending"))
        self.assertEqual(str(row[4]),"0.75")

    def test_two_bots_cannot_both_record_same_scoped_intent(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(self.record,
                                    ("daily","intraday","aggressive")))
        self.assertEqual(sum(r[0] for r in results),1)
        with self.admin() as db:
            counts=db.execute(
                "select (select count(*) from public.ci_scoped_entry_claims),"
                "(select count(*) from public.ci_scoped_entry_intents)"
            ).fetchone()
        self.assertEqual(counts,(1,1))

    def test_replay_and_competing_claims_cannot_replace_intent(self):
        old = uuid.uuid4()
        self.assertTrue(self.record(token=old)[0])
        self.assertEqual(self.record(token=old),(False,None,None))
        self.assertEqual(self.record("intraday",action="open_short"),(False,None,None))
        with self.admin() as db:
            saved=db.execute(
                "select bot,action,requested_size,intent_token "
                "from public.ci_scoped_entry_intents"
            ).fetchone()
        self.assertEqual(saved[0:2],("daily","open_long"))
        self.assertEqual(str(saved[2]),"2")
        self.assertEqual(saved[3],old)

    def test_invalid_sizes_dont_leave_half_claim(self):
        for size in ("0", "-1", "NaN", "Infinity"):
            with self.subTest(size=size):
                with self.assertRaises(InsufficientPrivilege):
                    self.record(size=size)
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_claims"
            ).fetchone()[0],0)
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_intents"
            ).fetchone()[0],0)

    def test_bot_cannot_change_intent_or_submit_order_in_database(self):
        self.assertTrue(self.record()[0])
        with self.bot("daily") as db:
            for table in ("public.ci_scoped_entry_claims",
                          "public.ci_scoped_entry_intents"):
                for privilege in ("SELECT","INSERT","UPDATE","DELETE"):
                    self.assertFalse(db.execute(
                        "select has_table_privilege(current_user,%s,%s)",
                        (table,privilege)
                    ).fetchone()[0])

    def test_account_scope_and_impersonation_are_rejected(self):
        with self.assertRaises(InsufficientPrivilege):
            self.record("daily",account=OTHER_ADDRESS)
        with self.bot("daily") as db:
            with self.assertRaises(InsufficientPrivilege):
                db.execute(
                    "select * from public.ci_record_pre_submit_intent("
                    "%s,%s,%s,%s,%s,%s,%s,%s)",
                    ("mainnet",ADDRESS,"","SOL","intraday",
                     uuid.uuid4(),"open_long","1"),
                )
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_claims"
            ).fetchone()[0],0)

    def test_undocumented_action_cannot_create_intent(self):
        for action in ("pyramid_long","close","open"):
            with self.subTest(action=action):
                with self.assertRaises(InsufficientPrivilege):
                    self.record(action=action)
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_intents"
            ).fetchone()[0],0)

if __name__ == "__main__":
    unittest.main()
