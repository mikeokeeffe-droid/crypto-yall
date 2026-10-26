import unittest
from unittest.mock import patch
from trusted_reconciler_dispatch_staging import dispatch_staging_reconciliation

class GatewayDispatchTests(unittest.TestCase):
    def setUp(self):
        self.options = dict(info=object(), address="offline", reconciler_rpc=object(),
                            signing_key=b"k"*32, issuer="issuer", audience="aud", now=100)

    def test_rejects_untrusted_dependencies_before_auth(self):
        for args in ({"rpc": object()}, {"authorized": True}, {"signing_key": b"x"}):
            with self.subTest(args=list(args)):
                with self.assertRaises(PermissionError):
                    dispatch_staging_reconciliation(
                        {"token": "invalid", "operation": "reconcile_entry", "args": args},
                        **self.options)

    def test_rejects_unknown_operation(self):
        with self.assertRaises(PermissionError):
            dispatch_staging_reconciliation(
                {"token": "invalid", "operation": "place_order", "args": {"x": 1}},
                **self.options)

    def test_rejects_bad_token_without_calling_adapter(self):
        with patch("trusted_reconciler_dispatch_staging._OPERATIONS", {"reconcile_entry": run}):
            with self.assertRaises(PermissionError):
                dispatch_staging_reconciliation(
                    {"token": "invalid", "operation": "reconcile_entry", "args": {"coin": "SOL", "bot": "intraday", "token": "owner", "order_id": "1", "order_start_ms": 1, "clock": 1}},
                    **self.options)
            run.assert_not_called()


    def test_verified_token_routes_only_to_server_owned_adapter(self):
        from unittest.mock import Mock
        run = Mock(return_value="reconciled")
        with patch("trusted_reconciler_dispatch_staging.verify_staging_jwt") as verify, \
             patch.dict("trusted_reconciler_dispatch_staging._OPERATIONS", {"reconcile_entry": run}):
            result = dispatch_staging_reconciliation(
                {"token": "signed", "operation": "reconcile_entry",
                 "args": {"coin": "SOL", "bot": "intraday", "token": "owner", "order_id": "1", "order_start_ms": 1, "clock": 1}},
                **self.options)
            self.assertEqual(result, "reconciled")
            verify.assert_called_once()
            run.assert_called_once()
            self.assertIs(run.call_args.args[2], self.options["reconciler_rpc"])
            self.assertEqual(run.call_args.kwargs["auth_token"], "signed")

    def test_rejects_release_with_invalid_token(self):
        with patch("trusted_reconciler_dispatch_staging._OPERATIONS", {"reconcile_release": run}):
            with self.assertRaises(PermissionError):
                dispatch_staging_reconciliation(
                    {"token": "invalid", "operation": "reconcile_release",
                     "args": {"coin": "SOL", "bot": "intraday", "token": "owner", "clock": 1}}, **self.options)
            run.assert_not_called()

    def test_rejects_unexpected_request_fields(self):
        with self.assertRaises(PermissionError):
            dispatch_staging_reconciliation(
                {"token": "invalid", "operation": "reconcile_entry",
                 "args": {"bot": "Intraday"}, "rpc": object()}, **self.options)


    def test_rejects_incomplete_arguments_before_verification(self):
        with patch("trusted_reconciler_dispatch_staging.verify_staging_jwt") as verify:
            with self.assertRaises(PermissionError):
                dispatch_staging_reconciliation(
                    {"token": "signed", "operation": "reconcile_entry",
                     "args": {"bot": "intraday"}}, **self.options)
            verify.assert_not_called()

    def test_rejects_other_bots_before_verification(self):
        for bot in ("aggressive", "daily"):
            with self.subTest(bot=bot):
                args = {"coin": "SOL", "bot": bot, "token": "owner",
                        "order_id": "1", "order_start_ms": 1, "clock": 1}
                with patch("trusted_reconciler_dispatch_staging.verify_staging_jwt") as verify:
                    with self.assertRaises(PermissionError):
                        dispatch_staging_reconciliation(
                            {"token": "signed", "operation": "reconcile_entry",
                             "args": args}, **self.options)
                    verify.assert_not_called()

if __name__ == "__main__":
    unittest.main()
