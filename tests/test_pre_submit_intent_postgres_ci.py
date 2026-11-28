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

    def bot(self, name, *, autocommit=False):
        return psycopg.connect(host="localhost", port=5432, dbname="safety_test",
                               user="entry_login_" + name,
                               password="disposable-" + name + "-only",
                               autocommit=autocommit)

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


    def test_real_sql_denials_preserve_committed_scoped_claim(self):
        """Each restricted bot must fail to read/edit/delete another's claim.

        Test actual PostgreSQL permissions, not only grant-catalog queries.
        A successful RPC must not confer direct table ownership or DML.
        """
        token = uuid.uuid4()
        self.assertTrue(self.record("daily", token=token)[0])
        with self.admin() as db:
            baseline = db.execute(
                "select c.bot,c.token,c.status,c.fence_token,"
                "i.bot,i.action,i.requested_size,i.status "
                "from public.ci_scoped_entry_claims c "
                "join public.ci_scoped_entry_intents i "
                "on i.intent_token=c.token"
            ).fetchall()
        self.assertEqual(len(baseline), 1)

        attempts = (
            ("select * from public.ci_scoped_entry_claims", ()),
            ("select * from public.ci_scoped_entry_intents", ()),
            ("select * from public.ci_scoped_executor_accounts", ()),
            ("update public.ci_scoped_entry_claims set status='filled' "
             "where token=%s", (token,)),
            ("delete from public.ci_scoped_entry_claims "
             "where token=%s", (token,)),
            ("update public.ci_scoped_entry_intents set requested_size=999 "
             "where intent_token=%s", (token,)),
            ("delete from public.ci_scoped_entry_intents "
             "where intent_token=%s", (token,)),
        )

        for bot in ("daily", "intraday", "aggressive"):
            with self.subTest(bot=bot), self.bot(bot, autocommit=True) as db:
                for sql, params in attempts:
                    with self.subTest(statement=sql.split()[0], table=sql.split()[3] if len(sql.split()) > 3 else sql):
                        with self.assertRaises(InsufficientPrivilege):
                            db.execute(sql, params)

        with self.admin() as db:
            after = db.execute(
                "select c.bot,c.token,c.status,c.fence_token,"
                "i.bot,i.action,i.requested_size,i.status "
                "from public.ci_scoped_entry_claims c "
                "join public.ci_scoped_entry_intents i "
                "on i.intent_token=c.token"
            ).fetchall()
        self.assertEqual(after, baseline)

    def test_undocumented_action_cannot_create_intent(self):
        for action in ("pyramid_long","close","open"):
            with self.subTest(action=action):
                with self.assertRaises(InsufficientPrivilege):
                    self.record(action=action)
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_intents"
            ).fetchone()[0],0)


    def _abrupt_child_claim(self, *, commit):
        """Use one disposable PostgreSQL session and exit without an ACK."""
        import subprocess
        import sys

        token = uuid.uuid4()
        script = """
import os, sys, uuid
import psycopg

# This code is run only by the disposable safety_test CI suite.
assert os.environ.get('ISOLATED_POSTGRES_CI') == '1'
assert os.environ.get('PGDATABASE') == 'safety_test'
with psycopg.connect(
    host='localhost', port=5432, dbname='safety_test',
    user='entry_login_daily', password='disposable-daily-only',
) as db:
    result = db.execute(
        'select recorded from public.ci_record_pre_submit_intent('
        '%s,%s,%s,%s,%s,%s,%s,%s)',
        ('mainnet', sys.argv[1], '', 'SOL', 'daily',
         uuid.UUID(sys.argv[2]), 'open_long', '2'),
    ).fetchone()
    assert result == (True,), result
    if sys.argv[3] == 'commit':
        db.commit()
    # Abrupt exit: no context-manager cleanup or client acknowledgement.
    # For 'abort', PostgreSQL must roll back the open transaction.
    os._exit(61 if sys.argv[3] == 'commit' else 62)
"""
        mode = "commit" if commit else "abort"
        child = subprocess.run(
            [sys.executable, "-c", script, ADDRESS, str(token), mode],
            check=False, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(child.returncode, 61 if commit else 62,
                         child.stdout + child.stderr)
        return token

    def _three_bot_recovery_race(self):
        """Three separate restricted PostgreSQL logins compete after restart."""
        from threading import Barrier

        bots = ("daily", "intraday", "aggressive")
        ready = Barrier(len(bots))

        def attempt(bot):
            ready.wait(timeout=10)
            return bot, self.record(bot, token=uuid.uuid4())

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            return list(pool.map(attempt, bots))

    def test_crash_before_commit_rolls_back_intent_then_one_bot_wins(self):
        """Uncommitted transaction must not leave a ghost claim or nonce."""
        self._abrupt_child_claim(commit=False)
        with self.admin() as db:
            self.assertEqual(
                db.execute(
                    "select count(*) from public.ci_scoped_entry_claims"
                ).fetchone()[0], 0)
            self.assertEqual(
                db.execute(
                    "select count(*) from public.ci_scoped_entry_intents"
                ).fetchone()[0], 0)
        decisions = self._three_bot_recovery_race()
        winners = [bot for bot, row in decisions if row[0]]
        self.assertEqual(len(winners), 1, decisions)
        self.assertEqual(sum(row == (False, None, None)
                             for _, row in decisions), 2, decisions)
        with self.admin() as db:
            rows = db.execute(
                "select c.bot,c.token,i.bot,i.intent_token "
                "from public.ci_scoped_entry_claims c "
                "join public.ci_scoped_entry_intents i "
                "on i.intent_token=c.token"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], winners[0])
        self.assertEqual(rows[0][2], winners[0])
        self.assertEqual(rows[0][1], rows[0][3])

    def test_crash_after_commit_without_ack_blocks_all_three_bots(self):
        """Committed intent survives client death; no replacement is allowed."""
        original_token = self._abrupt_child_claim(commit=True)
        with self.admin() as db:
            before = db.execute(
                "select c.bot,c.token,c.fence_token,i.intent_token,"
                "i.action,i.requested_size "
                "from public.ci_scoped_entry_claims c "
                "join public.ci_scoped_entry_intents i "
                "on i.intent_token=c.token"
            ).fetchall()
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0][0], "daily")
        self.assertEqual(before[0][1], original_token)
        self.assertEqual(before[0][3], original_token)
        self.assertEqual(before[0][4], "open_long")
        decisions = self._three_bot_recovery_race()
        self.assertEqual(
            [row for _, row in decisions],
            [(False, None, None)] * 3,
        )
        with self.admin() as db:
            after = db.execute(
                "select c.bot,c.token,c.fence_token,i.intent_token,"
                "i.action,i.requested_size "
                "from public.ci_scoped_entry_claims c "
                "join public.ci_scoped_entry_intents i "
                "on i.intent_token=c.token"
            ).fetchall()
        self.assertEqual(after, before)



    def _uncommitted_transaction_lock_timeout(self, *, owner_commits):
        """A second LOGIN cannot slip past a pending same-scope transaction.

        All SQL and credentials are confined to disposable safety_test CI.
        Never interprets a DB claim as permission to place an exchange order.
        """
        from psycopg.errors import LockNotAvailable

        first_token = uuid.uuid4()
        with self.bot("daily") as first:
            created = first.execute(
                "select recorded,intent_id,fencing "
                "from public.ci_record_pre_submit_intent("
                "%s,%s,%s,%s,%s,%s,%s,%s)",
                ("mainnet", ADDRESS, "", "SOL", "daily",
                 first_token, "open_long", "2"),
            ).fetchone()
            self.assertEqual(created[:2], (True, first_token))
            # Keep first transaction uncommitted while a different bot
            # attempts the same unique scope with a short lock timeout.
            with self.bot("intraday", autocommit=True) as competing:
                competing.execute("set lock_timeout = '400ms'")
                with self.assertRaises(LockNotAvailable):
                    competing.execute(
                        "select recorded,intent_id,fencing "
                        "from public.ci_record_pre_submit_intent("
                        "%s,%s,%s,%s,%s,%s,%s,%s)",
                        ("mainnet", ADDRESS, "", "SOL", "intraday",
                         uuid.uuid4(), "open_short", "1"),
                    )
            if owner_commits:
                first.commit()
            else:
                first.rollback()

        # A new session, representing recovery after the timeout:
        # committed owner must win permanently; rolled-back owner did not
        # claim anything and a fresh valid request is permitted in CI.
        retry = self.record(
            "intraday", action="open_short", size="1",
            token=uuid.uuid4(),
        )
        self.assertEqual(retry[0], not owner_commits)
        if owner_commits:
            self.assertEqual(retry, (False, None, None))
        else:
            self.assertIsNotNone(retry[1])
        with self.admin() as db:
            rows = db.execute(
                "select c.bot,c.token,i.bot,i.intent_token,i.action "
                "from public.ci_scoped_entry_claims c "
                "join public.ci_scoped_entry_intents i "
                "on i.intent_token=c.token"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "daily" if owner_commits else "intraday")
        self.assertEqual(rows[0][2], rows[0][0])
        self.assertEqual(rows[0][3], rows[0][1])
        self.assertEqual(rows[0][4], "open_long" if owner_commits else "open_short")

    def test_scoped_lock_timeout_then_owner_commit_blocks_retry(self):
        self._uncommitted_transaction_lock_timeout(owner_commits=True)

    def test_scoped_lock_timeout_then_owner_rollback_allows_one_retry(self):
        self._uncommitted_transaction_lock_timeout(owner_commits=False)



    def test_forced_backend_termination_rolls_back_and_three_bots_compete(self):
        """A terminated uncommitted DB session must not leave a phantom lock.

        PostgreSQL 16's pg_terminate_backend(pid, timeout_ms) waits for the
        backend to exit; only the disposable CI admin can terminate it.
        No exchange submission has occurred in this test.
        """
        token = uuid.uuid4()
        owner = self.bot("daily")
        try:
            pid = owner.execute("select pg_backend_pid()").fetchone()[0]
            claimed = owner.execute(
                "select recorded,intent_id,fencing "
                "from public.ci_record_pre_submit_intent("
                "%s,%s,%s,%s,%s,%s,%s,%s)",
                ("mainnet", ADDRESS, "", "SOL", "daily",
                 token, "open_long", "2"),
            ).fetchone()
            self.assertEqual(claimed[:2], (True, token))

            # This independent superuser session forcibly ends the still
            # uncommitted owner transaction. No client-side commit or retry.
            with self.admin() as administrator:
                ended = administrator.execute(
                    "select pg_terminate_backend(%s, 5000)",
                    (pid,),
                ).fetchone()[0]
                self.assertTrue(ended)
        finally:
            owner.close()

        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_claims"
            ).fetchone()[0], 0)
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_intents"
            ).fetchone()[0], 0)

        # Each retry creates a fresh SQL session using its own restricted bot
        # LOGIN. The DB must commit exactly one atomic scoped claim + intent.
        decisions = self._three_bot_recovery_race()
        winners = [bot for bot, result in decisions if result[0]]
        self.assertEqual(len(winners), 1, decisions)
        self.assertEqual(
            sum(result == (False, None, None)
                for _, result in decisions), 2, decisions)
        with self.admin() as db:
            rows = db.execute(
                "select c.bot,c.token,i.bot,i.intent_token "
                "from public.ci_scoped_entry_claims c "
                "join public.ci_scoped_entry_intents i "
                "on c.token=i.intent_token"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], winners[0])
        self.assertEqual(rows[0][2], winners[0])
        self.assertEqual(rows[0][1], rows[0][3])


if __name__ == "__main__":
    unittest.main()
