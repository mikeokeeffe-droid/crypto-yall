"""No real DB or exchange: restricted executor transport contract tests."""
import unittest
from uuid import uuid4

from trusted_executor_postgres_transport_staging import restricted_executor_rpc


class Cursor:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return self.value


class Transaction:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Connection:
    def __init__(self, identity):
        self.identity = identity
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def transaction(self):
        return Transaction()

    def execute(self, query, params=None):
        self.queries.append((query, params))
        if query == "select session_user, current_user":
            return Cursor(self.identity)
        return Cursor((True,))


class ExecutorTransportTests(unittest.TestCase):
    def setUp(self):
        self.conn = Connection(("executor_login_test", "executor_login_test"))
        self.rpc = restricted_executor_rpc(
            lambda: self.conn, expected_login="executor_login_test",
            expected_bot="intraday")
        self.params = dict(p_coin="BTC", p_bot="intraday",
                           p_token=str(uuid4()), p_ttl_seconds=120)

    def test_allowed_reservation_uses_bound_parameters(self):
        self.assertTrue(self.rpc("try_reserve_bot_entry", self.params))
        self.assertEqual(len(self.conn.queries), 2)
        self.assertEqual(self.conn.queries[1][1], tuple(self.params.values()))

    def test_unlisted_rpc_denied(self):
        with self.assertRaises(PermissionError):
            self.rpc("resolve_bot_entry_intent", self.params)
        self.assertEqual(self.conn.queries, [])

    def test_extra_parameters_denied(self):
        with self.assertRaises(PermissionError):
            self.rpc("try_reserve_bot_entry", dict(self.params, extra=True))

    def test_switched_or_wrong_identity_denied(self):
        self.conn.identity = ("postgres", "executor_login_test")
        with self.assertRaises(PermissionError):
            self.rpc("try_reserve_bot_entry", self.params)
        self.assertEqual(len(self.conn.queries), 1)

    def test_invalid_ttl_denied(self):
        with self.assertRaises(ValueError):
            self.rpc("try_reserve_bot_entry", dict(self.params, p_ttl_seconds=0))

    def test_privileged_expected_login_denied(self):
        with self.assertRaises(ValueError):
            restricted_executor_rpc(
                lambda: self.conn, expected_login="postgres",
                expected_bot="intraday")

    def test_login_cannot_reserve_for_another_bot(self):
        with self.assertRaises(PermissionError):
            self.rpc("try_reserve_bot_entry", dict(self.params, p_bot="daily"))
        self.assertEqual(self.conn.queries, [])


if __name__ == "__main__":
    unittest.main()
