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
        with patch("trusted_reconciler_dispatch_staging.reconcile_entry_with_token") as run:
            with self.assertRaises(PermissionError):
                dispatch_staging_reconciliation(
                    {"token": "invalid", "operation": "reconcile_entry", "args": {"bot": "Intraday"}},
                    **self.options)
            run.assert_not_called()

if __name__ == "__main__":
    unittest.main()
