"""Offline checks for staging dedicated-login transport. No real DB or orders."""
import unittest
from unittest.mock import MagicMock
from trusted_reconciler_postgres_transport_staging import restricted_reconciler_rpc


class TransportTests(unittest.TestCase):
    def test_rejects_privileged_login(self):
        for name in ("postgres", "service_role", "bot_reconciler"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                restricted_reconciler_rpc(lambda: None, expected_login=name)

    def test_rejects_unlisted_rpc_without_connecting(self):
        calls = []
        rpc = restricted_reconciler_rpc(
            lambda: calls.append(True), expected_login="reconciler_login_trial")
        with self.assertRaises(PermissionError):
            rpc("try_reserve_bot_entry", {})
        self.assertEqual(calls, [])

    def test_rejects_wrong_database_identity_before_mutation(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.transaction.return_value.__enter__.return_value = None
        conn.execute.return_value.fetchone.return_value = (
            "postgres", "bot_reconciler")
        rpc = restricted_reconciler_rpc(
            lambda: conn, expected_login="reconciler_login_trial")
        with self.assertRaises(PermissionError):
            rpc("record_bot_position_owner", {
                "p_coin": "SOL", "p_bot": "intraday",
                "p_token": "00000000-0000-4000-8000-000000000001",
                "p_exchange_order_id": "17", "p_fill_verified": True})
        self.assertEqual(conn.execute.call_count, 1)


if __name__ == "__main__":
    unittest.main()
