import unittest
from types import SimpleNamespace
from trusted_reconciler_db_adapter_staging import commit_candidate

class AdapterTests(unittest.TestCase):
    def test_verified_handoff(self):
        calls = []
        def rpc(fn, args):
            calls.append((fn, args))
            return True
        r = commit_candidate(rpc, SimpleNamespace(action="handoff_candidate"),
                             coin="SOL", bot="intraday", token="token", order_id=17)
        self.assertTrue(r.committed)
        self.assertEqual(calls[0][0], "record_bot_position_owner")
    def test_non_intraday_bots_denied_at_rpc_boundary(self):
        for bot in ("aggressive", "daily"):
            with self.subTest(bot=bot):
                calls = []
                result = commit_candidate(lambda *args: calls.append(args) or True,
                    SimpleNamespace(action="handoff_candidate"),
                    coin="SOL", bot=bot, token="token", order_id=17)
                self.assertFalse(result.committed)
                self.assertEqual(calls, [])

    def test_unverified_never_calls_rpc(self):
        calls = []
        r = commit_candidate(lambda *args: calls.append(args), SimpleNamespace(action="hold"),
                             coin="SOL", bot="intraday", token="token", order_id=17)
        self.assertFalse(r.committed)
        self.assertEqual(calls, [])
    def test_release_requires_separate_verification(self):
        r = commit_candidate(lambda *args: True, SimpleNamespace(action="release_candidate"),
                             coin="SOL", bot="intraday", token="token")
        self.assertFalse(r.committed)
    def test_transport_failure_keeps_intent(self):
        def fail(*args): raise ConnectionError()
        r = commit_candidate(fail, SimpleNamespace(action="handoff_candidate"),
                             coin="SOL", bot="intraday", token="token", order_id=17)
        self.assertFalse(r.committed)
    def test_ambiguous_database_result_rejected(self):
        r = commit_candidate(lambda *args: {"data": True}, SimpleNamespace(action="handoff_candidate"),
                             coin="SOL", bot="intraday", token="token", order_id=17)
        self.assertFalse(r.committed)
    def test_missing_order_id_rejected(self):
        r = commit_candidate(lambda *args: True, SimpleNamespace(action="handoff_candidate"),
                             coin="SOL", bot="intraday", token="token")
        self.assertFalse(r.committed)

if __name__ == "__main__":
    unittest.main()
