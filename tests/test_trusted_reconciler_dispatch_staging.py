import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from staging_executor_gateway_contract import BOTS
from trusted_reconciler_dispatch_staging import dispatch_staging_reconciliation


class GatewayDispatchTests(unittest.TestCase):
    def setUp(self):
        self.options = dict(
            info=object(),
            address="offline",
            reconciler_rpc=Mock(return_value={
                "status": "submitted",
                "exchange_order_id": "1",
                "submitted_at_ms": 1,
                "requested_size": 1.0,
            }),
            signing_keys={
                bot: f"{bot}-reconciler-key-32-bytes-minimum".encode()
                for bot in BOTS
            },
            issuer="issuer",
            audience="aud",
            now=100,
            clock=lambda: 1,
        )

    def request(self, operation="reconcile_entry", args=None, token="signed"):
        return {
            "token": token,
            "operation": operation,
            "args": args if args is not None else {
                "coin": "SOL", "bot": "intraday", "token": "owner",
            },
        }

    def test_rejects_untrusted_dependencies_before_auth(self):
        for args in (
            {"rpc": object()},
            {"authorized": True},
            {"signing_key": b"x"},
            {"clock": lambda: 1},
        ):
            with self.subTest(args=list(args)), self.assertRaises(PermissionError):
                dispatch_staging_reconciliation(
                    self.request(args=args), **self.options
                )

    def test_rejects_unknown_operation_and_unexpected_request_fields(self):
        with self.assertRaises(PermissionError):
            dispatch_staging_reconciliation(
                self.request(operation="place_order", args={"x": 1}),
                **self.options,
            )
        request = self.request()
        request["rpc"] = object()
        with self.assertRaises(PermissionError):
            dispatch_staging_reconciliation(request, **self.options)

    def test_rejects_bad_token_without_reading_intent_or_exchange(self):
        with self.assertRaises(PermissionError):
            dispatch_staging_reconciliation(
                self.request(token="invalid"), **self.options
            )
        self.options["reconciler_rpc"].assert_not_called()

    def test_verified_identity_loads_durable_intent_before_dispatch(self):
        run = Mock(return_value="reconciled")
        with patch(
            "trusted_reconciler_dispatch_staging.verify_staging_jwt",
            return_value=SimpleNamespace(subject="reconciler:intraday"),
        ) as verify, patch(
            "trusted_reconciler_dispatch_staging._OPERATIONS",
            {"reconcile_entry": run},
        ):
            result = dispatch_staging_reconciliation(
                self.request(), **self.options
            )
        self.assertEqual(result, "reconciled")
        verify.assert_called_once_with(
            "signed", self.options["signing_keys"]["intraday"],
            issuer="issuer", audience="aud", now=100,
        )
        self.options["reconciler_rpc"].assert_called_once_with(
            "get_bot_entry_reconciliation_intent",
            {"p_coin": "SOL", "p_bot": "intraday", "p_token": "owner"},
        )
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs["order_id"], "1")
        self.assertEqual(run.call_args.kwargs["requested_size"], 1.0)
        self.assertEqual(run.call_args.kwargs["clock"], self.options["clock"])

    def test_malformed_or_unknown_durable_order_stays_fenced(self):
        for intent in (
            None,
            {"status": "pending", "exchange_order_id": None,
             "submitted_at_ms": None, "requested_size": None},
            {"status": "uncertain", "exchange_order_id": None,
             "submitted_at_ms": 1, "requested_size": 1.0},
            {"status": "submitted", "exchange_order_id": "1x",
             "submitted_at_ms": 1, "requested_size": 1.0},
        ):
            with self.subTest(intent=intent):
                rpc = Mock(return_value=intent)
                options = {**self.options, "reconciler_rpc": rpc}
                operation = Mock()
                with patch(
                    "trusted_reconciler_dispatch_staging.verify_staging_jwt",
                    return_value=SimpleNamespace(subject="reconciler:intraday"),
                ), patch(
                    "trusted_reconciler_dispatch_staging._OPERATIONS",
                    {"reconcile_entry": operation},
                ):
                    result = dispatch_staging_reconciliation(
                        self.request(), **options
                    )
                self.assertFalse(result.confirmed)
                operation.assert_not_called()

    def test_reconciler_credentials_are_bot_specific(self):
        for bot in BOTS:
            with self.subTest(bot=bot):
                request = self.request(args={
                    "coin": "SOL", "bot": bot, "token": "owner",
                })
                with patch(
                    "trusted_reconciler_dispatch_staging.verify_staging_jwt",
                    return_value=SimpleNamespace(subject="reconciler:" + bot),
                ) as verify, patch(
                    "trusted_reconciler_dispatch_staging._OPERATIONS",
                    {"reconcile_entry": Mock(return_value="ok")},
                ):
                    dispatch_staging_reconciliation(request, **self.options)
                verify.assert_called_once_with(
                    "signed", self.options["signing_keys"][bot],
                    issuer="issuer", audience="aud", now=100,
                )

    def test_bot_mismatched_reconciler_identity_is_rejected_before_db(self):
        request = self.request(args={
            "coin": "SOL", "bot": "daily", "token": "owner",
        })
        self.options["reconciler_rpc"].reset_mock()
        with patch(
            "trusted_reconciler_dispatch_staging.verify_staging_jwt",
            return_value=SimpleNamespace(subject="reconciler:aggressive"),
        ), self.assertRaises(PermissionError):
            dispatch_staging_reconciliation(request, **self.options)
        self.options["reconciler_rpc"].assert_not_called()

    def test_release_operation_uses_server_clock_and_no_intent_load(self):
        run = Mock(return_value="released")
        with patch(
            "trusted_reconciler_dispatch_staging.verify_staging_jwt",
            return_value=SimpleNamespace(subject="reconciler:intraday"),
        ), patch(
            "trusted_reconciler_dispatch_staging._OPERATIONS",
            {"reconcile_release": run},
        ):
            result = dispatch_staging_reconciliation(
                self.request("reconcile_release"), **self.options
            )
        self.assertEqual(result, "released")
        self.options["reconciler_rpc"].assert_not_called()
        self.assertEqual(run.call_args.kwargs["clock"], self.options["clock"])


if __name__ == "__main__":
    unittest.main()
