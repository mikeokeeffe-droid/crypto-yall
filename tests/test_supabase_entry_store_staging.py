import unittest
import uuid
from entry_gate_staging import acquire_entry_permit
from supabase_entry_store_staging import SupabaseEntryReservationStore


class FakeRPC:
    def __init__(self, data=None, error=None):
        self.data = data
        self.error = error
    def execute(self):
        if self.error:
            raise self.error
        return self


class FakeClient:
    def __init__(self, replies):
        self.replies = replies
        self.calls = []
    def rpc(self, name, args):
        self.calls.append((name, args))
        return self.replies.pop(0)


class SupabaseAdapterTests(unittest.TestCase):
    def test_two_rpcs_same_token(self):
        client = FakeClient([FakeRPC(True), FakeRPC(True)])
        permit = acquire_entry_permit(
            SupabaseEntryReservationStore(client), "BTC", "aggressive"
        )
        self.assertIsNotNone(permit)
        self.assertEqual(
            client.calls[0][1]["p_token"], client.calls[1][1]["p_token"]
        )

    def test_rpc_false_denies(self):
        client = FakeClient([FakeRPC(False)])
        self.assertIsNone(acquire_entry_permit(
            SupabaseEntryReservationStore(client), "BTC", "intraday"
        ))

    def test_rpc_timeout_denies(self):
        client = FakeClient([FakeRPC(error=TimeoutError("RPC timeout"))])
        self.assertIsNone(acquire_entry_permit(
            SupabaseEntryReservationStore(client), "ETH", "daily"
        ))

    def test_unexpected_payload_denies(self):
        client = FakeClient([FakeRPC({"ok": True})])
        self.assertIsNone(acquire_entry_permit(
            SupabaseEntryReservationStore(client), "SOL", "aggressive"
        ))


if __name__ == "__main__":
    unittest.main()
