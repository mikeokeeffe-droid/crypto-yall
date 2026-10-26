import unittest
from unittest.mock import patch
from types import SimpleNamespace
from trusted_reconciler_service_staging import reconcile_submitted_entry, reconcile_flat_owner, authenticated_rpc, authorized_reconcile_submitted_entry, authorized_reconcile_flat_owner

ARGS = dict(coin="SOL", bot="intraday", token="durable-token", order_id=17,
            order_start_ms=99000, clock=lambda: 100)

class ServiceTests(unittest.TestCase):
    def test_unauthorized_entry_does_not_read_exchange_or_mutate(self):
        with patch("trusted_reconciler_service_staging.reconcile_entry") as exchange:
            with self.assertRaises(PermissionError):
                authorized_reconcile_submitted_entry(None, None, lambda *a: True, **ARGS)
            exchange.assert_not_called()

    def test_unauthorized_release_does_not_read_exchange_or_mutate(self):
        with patch("trusted_reconciler_service_staging.release_verified") as exchange:
            with self.assertRaises(PermissionError):
                authorized_reconcile_flat_owner(None, None, lambda *a: True,
                    coin="SOL", bot="intraday", token="durable-token", clock=lambda: 100)
            exchange.assert_not_called()

    def test_rpc_adapter_denies_missing_authorization(self):
        for authorized in (False, None, "true", 1):
            with self.subTest(authorized=authorized):
                with self.assertRaises(PermissionError):
                    authenticated_rpc(lambda *a: True, authorized=authorized)

    def test_rpc_adapter_allows_explicit_authorization(self):
        rpc = lambda *a: True
        self.assertIs(authenticated_rpc(rpc, authorized=True), rpc)

    def test_verified_entry_calls_trusted_rpc(self):
        calls = []
        with patch("trusted_reconciler_service_staging.reconcile_entry",
                   return_value=SimpleNamespace(action="handoff_candidate")):
            result = reconcile_submitted_entry(None, None,
                       lambda name, data: calls.append(name) or True, **ARGS)
        self.assertTrue(result.confirmed)
        self.assertEqual(calls, ["record_bot_position_owner"])

    def test_held_entry_never_mutates_database(self):
        calls = []
        with patch("trusted_reconciler_service_staging.reconcile_entry",
                   return_value=SimpleNamespace(action="hold", reason="incomplete fills")):
            result = reconcile_submitted_entry(None, None,
                       lambda name, data: calls.append(name) or True, **ARGS)
        self.assertFalse(result.confirmed)
        self.assertEqual(calls, [])

    def test_other_bot_rejected_before_evidence(self):
        result = reconcile_submitted_entry(None, None, lambda *a: True,
                   **{**ARGS, "bot": "aggressive"})
        self.assertFalse(result.confirmed)

    def test_entry_rejects_other_bots_without_exchange_or_rpc(self):
        for bot in ("aggressive", "daily", "", None):
            with self.subTest(bot=bot):
                with patch("trusted_reconciler_service_staging.reconcile_entry") as evidence:
                    rpc_calls = []
                    result = reconcile_submitted_entry(None, None,
                        lambda *a: rpc_calls.append(a) or True,
                        **{**ARGS, "bot": bot})
                self.assertFalse(result.confirmed)
                evidence.assert_not_called()
                self.assertEqual(rpc_calls, [])

    def test_release_rejects_other_bots_without_exchange_or_rpc(self):
        for bot in ("aggressive", "daily", "", None):
            with self.subTest(bot=bot):
                with patch("trusted_reconciler_service_staging.release_verified") as release:
                    rpc_calls = []
                    result = reconcile_flat_owner(None, None,
                        lambda *a: rpc_calls.append(a) or True,
                        coin="SOL", bot=bot, token="durable-token", clock=lambda: 100)
                self.assertFalse(result.confirmed)
                release.assert_not_called()
                self.assertEqual(rpc_calls, [])

    def test_release_holds_when_evidence_denied(self):
        with patch("trusted_reconciler_service_staging.release_verified", return_value=False):
            result = reconcile_flat_owner(None, None, lambda *a: True,
                        coin="SOL", bot="intraday", token="durable-token", clock=lambda: 100)
        self.assertFalse(result.confirmed)

if __name__ == "__main__":
    unittest.main()
