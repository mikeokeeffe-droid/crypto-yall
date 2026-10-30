"""Staging reconciliation workflow with fake Hyperliquid and synthetic identities."""
import base64
import hashlib
import hmac
import json
import unittest
import uuid

from staging_executor_gateway_contract import BOTS
from trusted_reconciler_dispatch_staging import dispatch_staging_reconciliation


ADDRESS = "0x" + "a" * 40
NOW_SECONDS = 100
START_MS = 99_000
BOT_ORDER = ("aggressive", "intraday", "daily")
KEYS = {
    bot: f"synthetic-{bot}-reconciler-key-at-least-32-bytes".encode()
    for bot in BOTS
}


def signed_token(bot):
    def encode(value):
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        ).rstrip(b"=").decode()

    header = encode({"alg": "HS256", "typ": "JWT"})
    claims = encode({
        "aud": "synthetic-staging-reconciler",
        "exp": 200,
        "iat": 90,
        "iss": "synthetic-staging-issuer",
        "nbf": 90,
        "scope": "reconciler:position-write",
        "sub": "reconciler:" + bot,
    })
    message = header + "." + claims
    signature = hmac.new(KEYS[bot], message.encode(), hashlib.sha256).digest()
    return message + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()


class FakeHyperliquid:
    def __init__(
        self,
        *,
        coin,
        order_id,
        status="filled",
        fills=(),
        position_size=0,
        open_orders=(),
        status_error=False,
        order_id_response=None,
        fills_error=False,
    ):
        self.coin = coin
        self.order_id = order_id
        self.status = status
        self.fills = list(fills)
        self.position_size = position_size
        self.open_orders_snapshot = list(open_orders)
        self.status_error = status_error
        self.order_id_response = order_id_response
        self.fills_error = fills_error
        self.exchange_reads = []
        self.order_submissions = 0

    def order_status(self, address, order_id):
        self.exchange_reads.append("order_status")
        if self.status_error:
            raise TimeoutError("synthetic status timeout")
        returned_id = (
            self.order_id
            if self.order_id_response is None
            else self.order_id_response
        )
        return {
            "status": "order",
            "order": {
                "order": {"coin": self.coin, "oid": returned_id},
                "status": self.status,
            },
        }

    def user_state(self, address):
        self.exchange_reads.append("user_state")
        if self.position_size == 0:
            positions = []
        else:
            positions = [{
                "position": {"coin": self.coin, "szi": str(self.position_size)}
            }]
        return {"assetPositions": positions}

    def open_orders(self, address):
        self.exchange_reads.append("open_orders")
        return list(self.open_orders_snapshot)

    def user_fills(self, address):
        self.exchange_reads.append("user_fills")
        return list(self.fills)

    def user_fills_by_time(self, address, start_ms, end_ms):
        self.exchange_reads.append("user_fills_by_time")
        if self.fills_error:
            raise TimeoutError("synthetic fill timeout")
        return [
            fill for fill in self.fills
            if start_ms <= fill.get("time", -1) <= end_ms
        ]


class DurableIntentStore:
    """Small persistent-state double matching the staging RPC boundaries."""

    def __init__(self):
        self.intents = {}
        self.reservations = {}
        self.owners = {}
        self.calls = []

    def add_intent(self, *, bot, coin, token=None, order_id, status="submitted",
                   requested_size=2, expires_at=NOW_SECONDS + 120):
        token = token or str(uuid.uuid4())
        self.intents[coin] = {
            "bot": bot,
            "token": token,
            "status": status,
            "exchange_order_id": order_id,
            "submitted_at_ms": START_MS,
            "requested_size": requested_size,
        }
        self.reservations[coin] = {
            "bot": bot, "token": token, "expires_at": expires_at,
        }
        return token

    def __call__(self, function, params):
        self.calls.append((function, dict(params)))
        if function == "get_bot_entry_reconciliation_intent":
            intent = self.intents.get(params["p_coin"])
            if (intent is None or intent["bot"] != params["p_bot"]
                    or intent["token"] != params["p_token"]):
                return None
            return {
                "status": intent["status"],
                "exchange_order_id": intent["exchange_order_id"],
                "submitted_at_ms": intent["submitted_at_ms"],
                "requested_size": intent["requested_size"],
            }
        if function == "record_bot_position_owner":
            intent = self.intents.get(params["p_coin"])
            if (intent is None or intent["bot"] != params["p_bot"]
                    or intent["token"] != params["p_token"]
                    or intent["exchange_order_id"] != params["p_exchange_order_id"]
                    or params["p_fill_verified"] is not True):
                return False
            existing = self.owners.get(params["p_coin"])
            identity = (
                params["p_bot"], params["p_token"],
                params["p_exchange_order_id"],
            )
            if existing is not None and existing != identity:
                return False
            self.intents[params["p_coin"]]["status"] = "filled"
            self.owners[params["p_coin"]] = identity
            return True
        if function == "release_resolved_bot_entry_intent":
            intent = self.intents.get(params["p_coin"])
            if (
                intent is None
                or intent["bot"] != params["p_bot"]
                or intent["token"] != params["p_token"]
                or intent["exchange_order_id"] != params["p_exchange_order_id"]
                or intent["status"] not in {"submitted", "uncertain"}
                or params["p_final_status"] not in {
                    "canceled", "cancelled", "rejected", "expired",
                }
                or any(params[name] is not True for name in (
                    "p_zero_fills", "p_exchange_flat", "p_no_open_orders",
                ))
                or params["p_coin"] in self.owners
            ):
                return False
            del self.intents[params["p_coin"]]
            self.reservations.pop(params["p_coin"], None)
            return True
        if function == "mark_bot_position_closed":
            owner = self.owners.get(params["p_coin"])
            if (owner is None or any(params[name] is not True for name in (
                "p_exchange_flat", "p_no_open_orders",
            ))):
                return False
            return True
        if function == "release_closed_bot_position":
            owner = self.owners.get(params["p_coin"])
            if owner is None:
                return False
            del self.owners[params["p_coin"]]
            self.intents.pop(params["p_coin"], None)
            self.reservations.pop(params["p_coin"], None)
            return True
        raise PermissionError("fake database RPC is not allowlisted")


def run_reconciliation(store, info, *, bot, coin, token, clock=lambda: NOW_SECONDS):
    return dispatch_staging_reconciliation(
        {
            "token": signed_token(bot),
            "operation": "reconcile_entry",
            "args": {"coin": coin, "bot": bot, "token": token},
        },
        info=info,
        address=ADDRESS,
        reconciler_rpc=store,
        signing_keys=KEYS,
        issuer="synthetic-staging-issuer",
        audience="synthetic-staging-reconciler",
        now=NOW_SECONDS,
        clock=clock,
    )


def fill(coin, order_id, size, trade_id=1):
    return {
        "coin": coin,
        "oid": order_id,
        "sz": str(size),
        "time": START_MS + 100,
        "tid": trade_id,
    }


class ThreeBotOfflineWorkflowTests(unittest.TestCase):
    def test_full_and_partial_fills_handoff_idempotently_for_every_bot(self):
        scenarios = (
            ("aggressive", "SOL", "filled", 2, 2),
            ("intraday", "ETH", "canceled", 0.75, 0.75),
            ("daily", "AVAX", "filled", 1.25, 1.25),
        )
        for bot, coin, status, filled_size, position_size in scenarios:
            with self.subTest(bot=bot):
                store = DurableIntentStore()
                order_id = str(10 + BOT_ORDER.index(bot))
                token = store.add_intent(
                    bot=bot, coin=coin, order_id=order_id, requested_size=2,
                )
                exchange = FakeHyperliquid(
                    coin=coin,
                    order_id=order_id,
                    status=status,
                    fills=[fill(coin, order_id, filled_size)],
                    position_size=position_size,
                )
                first = run_reconciliation(
                    store, exchange, bot=bot, coin=coin, token=token,
                )
                second = run_reconciliation(
                    store, exchange, bot=bot, coin=coin, token=token,
                )
                self.assertTrue(first.confirmed, first.reason)
                self.assertTrue(second.confirmed, second.reason)
                self.assertEqual(len(store.owners), 1)
                self.assertEqual(store.intents[coin]["status"], "filled")
                self.assertEqual(exchange.order_submissions, 0)
                self.assertEqual(
                    [name for name, _ in store.calls].count("record_bot_position_owner"),
                    2,
                )

    def test_final_cancel_and_rejection_release_only_verified_zero_fill(self):
        for bot, status in (
            ("aggressive", "canceled"),
            ("intraday", "rejected"),
            ("daily", "expired"),
        ):
            with self.subTest(bot=bot, status=status):
                store = DurableIntentStore()
                coin = bot.upper()
                token = store.add_intent(
                    bot=bot, coin=coin, order_id="22",
                    expires_at=NOW_SECONDS - 500,
                )
                exchange = FakeHyperliquid(
                    coin=coin, order_id="22", status=status,
                )
                result = run_reconciliation(
                    store, exchange, bot=bot, coin=coin, token=token,
                )
                self.assertTrue(result.confirmed, result.reason)
                self.assertNotIn(coin, store.intents)
                self.assertNotIn(coin, store.reservations)
                self.assertEqual(
                    [name for name, _ in store.calls].count(
                        "release_resolved_bot_entry_intent"
                    ),
                    1,
                )
                self.assertEqual(exchange.order_submissions, 0)

    def test_timeout_unknown_order_and_restart_keep_expired_intent_fenced(self):
        store = DurableIntentStore()
        token = store.add_intent(
            bot="daily", coin="BTC", order_id="77", status="uncertain",
            expires_at=NOW_SECONDS - 3600,
        )
        timeout = FakeHyperliquid(
            coin="BTC", order_id="77", status_error=True,
        )
        for _ in range(2):
            result = run_reconciliation(
                store, timeout, bot="daily", coin="BTC", token=token,
            )
            self.assertFalse(result.confirmed)
            self.assertIn("BTC", store.intents)
        self.assertNotIn("record_bot_position_owner",
                         [name for name, _ in store.calls])
        self.assertNotIn("release_resolved_bot_entry_intent",
                         [name for name, _ in store.calls])

        alternate = store.add_intent(
            bot="aggressive", coin="XRP", order_id="88",
        )
        self.assertNotEqual(alternate, token)
        # A durable intent is the cross-bot fence even after its short lease expires.
        self.assertEqual(store.intents["BTC"]["status"], "uncertain")
        self.assertEqual(store.reservations["BTC"]["expires_at"], NOW_SECONDS - 3600)
        timeout.status_error = False
        timeout.status = "canceled"
        recovered = run_reconciliation(
            store, timeout, bot="daily", coin="BTC", token=token,
        )
        self.assertTrue(recovered.confirmed, recovered.reason)
        self.assertNotIn("BTC", store.intents)

    def test_unknown_order_mismatch_open_orders_and_bad_fill_pages_hold(self):
        cases = (
            FakeHyperliquid(
                coin="SOL", order_id="31", status="canceled",
                order_id_response="32",
            ),
            FakeHyperliquid(
                coin="SOL", order_id="31", status="canceled",
                open_orders=[{"coin": "SOL", "oid": "other"}],
            ),
            FakeHyperliquid(
                coin="SOL", order_id="31", status="canceled",
                fills_error=True,
            ),
        )
        for exchange in cases:
            with self.subTest(exchange=exchange):
                store = DurableIntentStore()
                token = store.add_intent(
                    bot="intraday", coin="SOL", order_id="31",
                )
                result = run_reconciliation(
                    store, exchange, bot="intraday", coin="SOL", token=token,
                )
                self.assertFalse(result.confirmed)
                self.assertIn("SOL", store.intents)
                self.assertFalse(store.owners)
                self.assertNotIn(
                    "release_resolved_bot_entry_intent",
                    [name for name, _ in store.calls],
                )

    def test_nonfinal_order_and_partial_fills_without_position_never_release(self):
        store = DurableIntentStore()
        token = store.add_intent(
            bot="aggressive", coin="SOL", order_id="31",
        )
        exchange = FakeHyperliquid(
            coin="SOL", order_id="31", status="open",
            fills=[fill("SOL", "31", 1)],
            position_size=0,
        )
        result = run_reconciliation(
            store, exchange, bot="aggressive", coin="SOL", token=token,
        )
        self.assertFalse(result.confirmed)
        self.assertIn("SOL", store.intents)
        self.assertFalse(store.owners)
        self.assertNotIn(
            "release_resolved_bot_entry_intent",
            [name for name, _ in store.calls],
        )

    def test_second_flat_check_must_remain_fresh_and_clear(self):
        store = DurableIntentStore()
        token = store.add_intent(
            bot="intraday", coin="SOL", order_id="31",
        )
        exchange = FakeHyperliquid(
            coin="SOL", order_id="31", status="canceled",
        )
        original_open_orders = exchange.open_orders
        read_count = 0

        def orders_change_after_first_check(address):
            nonlocal read_count
            read_count += 1
            if read_count >= 2:
                return [{"coin": "SOL", "oid": "late-open"}]
            return original_open_orders(address)

        exchange.open_orders = orders_change_after_first_check
        result = run_reconciliation(
            store, exchange, bot="intraday", coin="SOL", token=token,
        )
        self.assertFalse(result.confirmed)
        self.assertIn("SOL", store.intents)
        self.assertNotIn(
            "release_resolved_bot_entry_intent",
            [name for name, _ in store.calls],
        )


if __name__ == "__main__":
    unittest.main()
