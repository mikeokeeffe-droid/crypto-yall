"""Real, restricted PostgreSQL LOGIN acceptance. Disposable safety_test only."""
import concurrent.futures
import os
import unittest
import uuid
import psycopg
from shared_entry_admission import claim_shared_entry
from restricted_shared_entry_postgres_ci import RestrictedPostgresEntryCoordinator

BOTS = ("daily", "intraday", "aggressive")

@unittest.skipUnless(os.getenv("ISOLATED_POSTGRES_CI") == "1" and
                     os.getenv("PGDATABASE") == "safety_test", "disposable CI only")
class DedicatedLoginAdmissionTests(unittest.TestCase):
    def setUp(self):
        # Disposable database only: isolate each test from previous test claims.
        with psycopg.connect(host="localhost", port=5432, dbname="safety_test",
                             user="postgres", password=os.environ["PGPASSWORD"],
                             autocommit=True) as admin:
            admin.execute("truncate public.bot_entry_intents, public.bot_entry_reservations")

    def factory(self, bot):
        def connect():
            return psycopg.connect(host="localhost", port=5432, dbname="safety_test",
                                   user="entry_login_" + bot,
                                   password="disposable-" + bot + "-only")
        return connect

    def coordinator(self, bot, factory=None):
        return RestrictedPostgresEntryCoordinator(
            factory or self.factory(bot), expected_bot=bot,
            expected_login="entry_login_" + bot)

    def test_three_distinct_sessions_compete_for_same_coin(self):
        def attempt(bot):
            return claim_shared_entry(self.coordinator(bot), bot=bot, coin="SOL",
                                      action="open_long", request_id=str(uuid.uuid4()))
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            decisions = list(pool.map(attempt, BOTS))
        self.assertEqual(sum(d.accepted for d in decisions), 1)

    def test_fencing_evidence_is_database_generated(self):
        result = claim_shared_entry(self.coordinator("aggressive"), bot="aggressive",
                                    coin="AVAX", action="pyramid_long",
                                    request_id=str(uuid.uuid4()))
        self.assertTrue(result.accepted)
        self.assertGreater(result.fence_token, 0)
        self.assertFalse(claim_shared_entry(
            self.coordinator("daily"), bot="daily", coin="AVAX",
            action="open_short", request_id=str(uuid.uuid4())).accepted)

    def test_login_cannot_claim_as_other_bot(self):
        req = str(uuid.uuid4())
        self.assertFalse(claim_shared_entry(
            self.coordinator("daily"), bot="intraday", coin="BTC",
            action="open_long", request_id=req).accepted)

    def test_identity_spoof_via_coordinator_is_denied(self):
        wrong = self.coordinator("intraday", self.factory("daily"))
        self.assertFalse(claim_shared_entry(
            wrong, bot="intraday", coin="LINK", action="open_long",
            request_id=str(uuid.uuid4())).accepted)

    def test_no_direct_table_writes_or_resolve(self):
        for bot in BOTS:
            with self.subTest(bot=bot), self.factory(bot)() as db:
                for table in ("bot_entry_intents", "bot_entry_reservations",
                              "bot_entry_executor_identities"):
                    self.assertFalse(db.execute(
                        "select has_table_privilege(current_user,%s,'INSERT')",
                        ("public." + table,)).fetchone()[0])
                    self.assertFalse(db.execute(
                        "select has_table_privilege(current_user,%s,'DELETE')",
                        ("public." + table,)).fetchone()[0])
                self.assertFalse(db.execute(
                    "select has_function_privilege(current_user,"
                    "'public.resolve_bot_entry_intent(text,text,uuid)','EXECUTE')"
                    ).fetchone()[0])

    def test_claim_proof_is_readable_only_by_the_owning_login(self):
        owner = claim_shared_entry(
            self.coordinator("daily"), bot="daily", coin="SOL",
            action="open_long", request_id=str(uuid.uuid4())
        )
        self.assertTrue(owner.accepted, owner.reason)
        token = uuid.UUID(owner.intent_id)
        with self.factory("daily")() as db:
            own = db.execute(
                "select bot,coin,token,status,fence_token "
                "from public.read_bot_entry_claim_proof(%s,%s,%s)",
                ("SOL", "daily", token),
            ).fetchone()
            self.assertEqual(own, ("daily", "SOL", token, "pending", owner.fence_token))
            self.assertFalse(db.execute(
                "select has_table_privilege(current_user,"
                "'public.bot_entry_intents','SELECT')"
            ).fetchone()[0])
        with self.factory("intraday")() as db:
            self.assertFalse(db.execute(
                "select has_table_privilege(current_user,"
                "'public.bot_entry_intents','SELECT')"
            ).fetchone()[0])
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                db.execute(
                    "select * from public.read_bot_entry_claim_proof(%s,%s,%s)",
                    ("SOL", "daily", token),
                )
        with self.factory("daily")() as db:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                db.execute(
                    "select * from public.bot_entry_intents where coin='SOL'"
                )

    def test_timeout_fails_closed(self):
        class Unavailable:
            def claim_intent(self, **kwargs):
                raise TimeoutError("commit unknown")
        result=claim_shared_entry(Unavailable(), bot="daily", coin="XRP",
                                  action="open_long",request_id=str(uuid.uuid4()))
        self.assertFalse(result.accepted)

if __name__ == "__main__":
    unittest.main()
