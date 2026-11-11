"""Disposable PostgreSQL account-scope claim tests; no exchange access."""
import concurrent.futures
import os
import unittest
import uuid
import psycopg
from psycopg.errors import InsufficientPrivilege

ADDRESS_A = "0x" + "1" * 40
ADDRESS_B = "0x" + "2" * 40


@unittest.skipUnless(
    os.getenv("ISOLATED_POSTGRES_CI") == "1" and
    os.getenv("PGDATABASE") == "safety_test",
    "Only the disposable safety_test database",
)
class ScopedEntryAdmissionTests(unittest.TestCase):
    def admin(self):
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="postgres", password=os.environ["PGPASSWORD"], autocommit=True,
        )

    def connect(self, bot):
        return psycopg.connect(
            host="localhost", port=5432, dbname="safety_test",
            user="entry_login_" + bot,
            password="disposable-" + bot + "-only",
        )

    def setUp(self):
        with self.admin() as db:
            db.execute("truncate public.ci_scoped_entry_intents, "
                       "public.ci_scoped_entry_claims")

    def claim(self, bot, *, environment="mainnet", account=ADDRESS_A,
              dex="", coin="SOL", token=None):
        token = token or uuid.uuid4()
        with self.connect(bot) as db:
            return db.execute(
                "select accepted,claim_id,fencing "
                "from public.ci_claim_scoped_entry(%s,%s,%s,%s,%s,%s)",
                (environment, account, dex, coin, bot, token),
            ).fetchone()

    def test_three_bots_compete_one_account_coin(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(self.claim, ("daily","intraday","aggressive")))
        self.assertEqual(sum(result[0] for result in results), 1)
        with self.admin() as db:
            rows = db.execute(
                "select environment,effective_account,coin,status "
                "from public.ci_scoped_entry_claims"
            ).fetchall()
        self.assertEqual(rows, [("mainnet", ADDRESS_A, "SOL", "pending")])

    def test_distinct_allowlisted_accounts_are_isolated(self):
        self.assertTrue(self.claim("daily",account=ADDRESS_A)[0])
        self.assertTrue(self.claim("intraday",account=ADDRESS_B)[0])
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_claims"
            ).fetchone()[0], 2)

    def test_mainnet_and_testnet_are_isolated(self):
        self.assertTrue(self.claim("daily", environment="mainnet")[0])
        self.assertTrue(self.claim("daily", environment="testnet")[0])

    def test_competing_claim_cannot_use_old_token(self):
        first_token = uuid.uuid4()
        first = self.claim("daily", token=first_token)
        self.assertTrue(first[0])
        second = self.claim("daily",token=first_token)
        self.assertEqual(second,(False,None,None))
        intraday = self.claim("intraday")
        self.assertEqual(intraday,(False,None,None))

    def test_foreign_account_and_nondefault_dex_rejected(self):
        with self.assertRaises(InsufficientPrivilege):
            self.claim("aggressive",account=ADDRESS_B)
        with self.assertRaises(InsufficientPrivilege):
            self.claim("daily",dex="other")
        with self.assertRaises(InsufficientPrivilege):
            self.claim("intraday",account="0x" + "A"*40)
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_claims"
            ).fetchone()[0],0)

    def test_wrong_environment_not_allowlisted(self):
        with self.assertRaises(InsufficientPrivilege):
            self.claim("intraday",environment="testnet")

    def test_bot_login_cannot_modify_or_read_claims_directly(self):
        with self.connect("daily") as db:
            for target in ("public.ci_scoped_entry_claims",
                           "public.ci_scoped_executor_accounts"):
                for priv in ("SELECT","INSERT","UPDATE","DELETE"):
                    self.assertFalse(db.execute(
                        "select has_table_privilege(current_user,%s,%s)",
                        (target, priv),
                    ).fetchone()[0])

    def test_concurrent_claims_on_two_accounts_do_not_cross_block(self):
        # Exactly one winner per independently allowlisted account.
        contenders = (
            ("daily", ADDRESS_A), ("aggressive", ADDRESS_A),
            ("intraday", ADDRESS_A), ("intraday", ADDRESS_B),
        )
        def attempt(item):
            bot, account = item
            return account, self.claim(bot, account=account)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(attempt, contenders))
        self.assertEqual(sum(result[1][0] for result in results), 2)
        for account in (ADDRESS_A, ADDRESS_B):
            self.assertEqual(
                sum(result[1][0] for result in results if result[0] == account),
                1,
            )
        with self.admin() as db:
            rows = db.execute(
                "select effective_account,coin,status "
                "from public.ci_scoped_entry_claims order by effective_account"
            ).fetchall()
        self.assertEqual(rows, [
            (ADDRESS_A, "SOL", "pending"), (ADDRESS_B, "SOL", "pending"),
        ])

    def test_same_token_cannot_be_replayed_across_environments(self):
        # A request UUID is single-use even when scopes are distinct.
        token = uuid.uuid4()
        self.assertTrue(
            self.claim("daily", environment="mainnet", token=token)[0]
        )
        self.assertEqual(
            self.claim("daily", environment="testnet", token=token),
            (False, None, None),
        )
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_claims"
            ).fetchone()[0], 1)

    def test_login_cannot_spoof_another_bot_for_same_account(self):
        with self.connect("daily") as db:
            with self.assertRaises(InsufficientPrivilege):
                db.execute(
                    "select * from public.ci_claim_scoped_entry(%s,%s,%s,%s,%s,%s)",
                    ("mainnet", ADDRESS_A, "", "SOL", "intraday", uuid.uuid4()),
                )
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select count(*) from public.ci_scoped_entry_claims"
            ).fetchone()[0], 0)

    def test_durable_unknown_claim_stays_a_fence(self):
        self.assertTrue(self.claim("aggressive")[0])
        with self.admin() as db:
            db.execute(
                "update public.ci_scoped_entry_claims set status='uncertain'"
                " where coin='SOL' and effective_account=%s",
                (ADDRESS_A,),
            )
        self.assertEqual(self.claim("intraday"),(False,None,None))
        with self.admin() as db:
            self.assertEqual(db.execute(
                "select status from public.ci_scoped_entry_claims"
            ).fetchone()[0],"uncertain")


    def test_untrusted_login_cannot_bypass_scoped_entry_permissions(self):
        """Unrelated CI-only login cannot call definer RPCs or touch claims.

        Real PostgreSQL privilege denial complements the per-bot checks.
        This disposable account has NO exchange or production credentials.
        """
        outsider = "ci_untrusted_scoped_probe"
        password = "disposable-untrusted-probe-only"
        signatures = (
            "public.ci_claim_scoped_entry(text,text,text,text,text,uuid)",
            "public.ci_record_pre_submit_intent("
            "text,text,text,text,text,uuid,text,numeric)",
        )
        with self.admin() as db:
            for role in ("anon", "authenticated", "service_role"):
                for signature in signatures:
                    with self.subTest(role=role, function=signature):
                        self.assertFalse(db.execute(
                            "select has_function_privilege(%s,%s,'EXECUTE')",
                            (role, signature),
                        ).fetchone()[0])
            db.execute(
                "create role ci_untrusted_scoped_probe "
                "login noinherit password 'disposable-untrusted-probe-only'"
            )
            db.execute("grant usage on schema public to ci_untrusted_scoped_probe")
        try:
            with psycopg.connect(
                host="localhost", port=5432, dbname="safety_test",
                user=outsider, password=password, autocommit=True,
            ) as attacker:
                self.assertEqual(
                    attacker.execute(
                        "select session_user,current_user").fetchone(),
                    (outsider, outsider),
                )
                with self.assertRaises(InsufficientPrivilege):
                    attacker.execute(
                        "select * from public.ci_claim_scoped_entry("
                        "%s,%s,%s,%s,%s,%s)",
                        ("mainnet", ADDRESS_A, "", "SOL", "daily",
                         uuid.uuid4()),
                    )
                with self.assertRaises(InsufficientPrivilege):
                    attacker.execute(
                        "select * from public.ci_record_pre_submit_intent("
                        "%s,%s,%s,%s,%s,%s,%s,%s)",
                        ("mainnet", ADDRESS_A, "", "SOL", "daily",
                         uuid.uuid4(), "open_long", "1"),
                    )
                for table in (
                    "public.ci_scoped_executor_accounts",
                    "public.ci_scoped_entry_claims",
                    "public.ci_scoped_entry_intents",
                    "public.bot_entry_executor_identities",
                ):
                    with self.subTest(table=table):
                        with self.assertRaises(InsufficientPrivilege):
                            attacker.execute("select * from " + table)
                with self.assertRaises(InsufficientPrivilege):
                    attacker.execute("set role entry_login_daily")
                with self.assertRaises(InsufficientPrivilege):
                    attacker.execute("set role postgres")
        finally:
            with self.admin() as db:
                db.execute(
                    "revoke usage on schema public from ci_untrusted_scoped_probe"
                )
                db.execute("drop role ci_untrusted_scoped_probe")
        with self.admin() as db:
            self.assertEqual(
                db.execute(
                    "select count(*) from public.ci_scoped_entry_claims"
                ).fetchone()[0], 0)
            self.assertEqual(
                db.execute(
                    "select count(*) from public.ci_scoped_entry_intents"
                ).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
