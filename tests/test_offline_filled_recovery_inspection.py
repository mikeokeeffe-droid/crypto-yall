"""Fake-only restart recovery tests. No network, exchange or database writes."""
import copy
import unittest

from offline_filled_recovery_inspection import inspect_possible_filled_recovery


def scenario():
    intent = dict(bot="daily", coin="SOL", token="claim-1", fence_token=42, status="uncertain",
                  action="open_long", exchange_order_id="123",
                  submitted_at_ms=100_000, requested_size="2")
    flat = dict(account="test-account", coin="SOL", fresh=True,
                complete=True, open_orders=[])
    before = dict(flat, bot="daily", token="claim-1", fence_token=42, capture_id="pre", observed_at_ms=99_000,
                  position_size="0")
    fill = dict(account="test-account", coin="SOL", order_id="123",
                side="long", fill_id="fill1", size="2", time_ms=100_100)
    first = dict(flat, capture_id="first", observed_at_ms=101_000,
                 position_size="2", fills_complete=True, fills=[fill])
    second = dict(flat, capture_id="second", observed_at_ms=102_000,
                  position_size="2", fills_complete=True,
                  fills=[dict(fill)])
    order = dict(account="test-account", coin="SOL", order_id="123",
                 side="long", status="filled", final=True, complete=True,
                 filled_size="2")
    return intent, before, order, first, second


class RecordedIntentReader:
    def __init__(self, intent, baseline):
        self.intent = intent
        self.baseline = baseline
        self.intent_reads = 0
        self.baseline_reads = 0

    def read_intent(self, **kwargs):
        self.intent_reads += 1
        return copy.deepcopy(self.intent)

    def read_pre_submit_capture(self, **kwargs):
        self.baseline_reads += 1
        return copy.deepcopy(self.baseline)


class ReadOnlyExchange:
    def __init__(self, order, first, second):
        self.order, self.captures = order, [first, second]
        self.order_reads = 0
        self.capture_reads = 0

    def read_order(self, **kwargs):
        self.order_reads += 1
        return copy.deepcopy(self.order)

    def capture_position_orders_fills(self, **kwargs):
        index = self.capture_reads
        self.capture_reads += 1
        return copy.deepcopy(self.captures[min(index, 1)])


class FilledRecoveryInspectionTests(unittest.TestCase):
    def setUp(self):
        intent, before, order, first, second = scenario()
        self.reader = RecordedIntentReader(intent, before)
        self.exchange = ReadOnlyExchange(order, first, second)

    def review(self, **kwargs):
        args = dict(
            intent_reader=self.reader, exchange_reader=self.exchange,
            bot="daily", coin="SOL", token="claim-1", expected_fence_token=42,
            account="test-account", now_ms=103_000,
        )
        return inspect_possible_filled_recovery(**dict(args, **kwargs))

    def test_matching_synthetic_full_fill_is_only_handoff_candidate(self):
        result = self.review()
        self.assertEqual(result.status, "handoff_candidate")
        self.assertEqual(self.reader.intent_reads, 2)
        self.assertEqual(self.reader.baseline_reads, 2)
        self.assertEqual(self.exchange.order_reads, 2)
        self.assertEqual(self.exchange.capture_reads, 2)

    def test_missing_pre_submit_capture_blocks_without_exchange_access(self):
        self.reader.baseline = None
        self.assertEqual(self.review().status, "hold")
        self.assertEqual(self.exchange.order_reads, 0)

    def test_stale_or_foreign_baseline_blocks(self):
        for changes in (
            {"position_size": "2"},
            {"account": "other-account"},
            {"observed_at_ms": 1},
            {"observed_at_ms": 105_000},
        ):
            with self.subTest(changes=changes):
                self.setUp()
                self.reader.baseline.update(changes)
                self.assertEqual(self.review().status, "hold")

    def test_pre_submit_baseline_must_belong_to_exact_bot_and_claim(self):
        for changes in (
            {"bot": "intraday"},
            {"token": "other-claim"},
            {"coin": "BTC"},
        ):
            with self.subTest(changes=changes):
                self.setUp()
                self.reader.baseline.update(changes)
                self.assertEqual(self.review().status, "hold")
                self.assertEqual(self.exchange.order_reads, 0)

    def test_stale_or_mismatched_fence_blocks(self):
        for invalid in (0, -1, 43, None, True):
            with self.subTest(invalid=invalid):
                self.setUp()
                self.reader.intent["fence_token"] = invalid
                self.assertEqual(self.review().status, "hold")
                self.assertEqual(self.exchange.order_reads, 0)
        self.setUp()
        self.reader.baseline["fence_token"] = 41
        self.assertEqual(self.review().status, "hold")
        self.assertEqual(self.exchange.order_reads, 0)
        self.setUp()
        self.assertEqual(self.review(expected_fence_token=41).status, "hold")

    def test_incomplete_or_foreign_fill_blocks(self):
        for changes in (
            {"order_id": "other-order"},
            {"size": "1"},
            {"account": "other-account"},
            {"time_ms": 100_000 - 1},
        ):
            with self.subTest(changes=changes):
                self.setUp()
                self.exchange.captures[0]["fills"][0].update(changes)
                self.assertEqual(self.review().status, "hold")

    def test_restart_cannot_adopt_same_side_manual_or_other_bot_fill(self):
        # A matching SOL long is insufficient to establish bot ownership.
        for side in ("long", "short"):
            with self.subTest(competing_side=side):
                self.setUp()
                foreign = dict(
                    account="test-account", coin="SOL", order_id="manual-999",
                    side=side, fill_id="manual-fill-1", size="1",
                    time_ms=100_150,
                )
                for capture in self.exchange.captures:
                    capture["fills"].append(dict(foreign))
                result = self.review()
                self.assertEqual(result.status, "hold")

    def test_restart_history_completeness_flag_missing_or_false_holds(self):
        for value in (False, None):
            with self.subTest(value=value):
                self.setUp()
                for capture in self.exchange.captures:
                    capture["fills_complete"] = value
                self.assertEqual(self.review().status, "hold")

    def test_restart_unexpected_position_delta_holds_even_with_matching_order(self):
        for value in ("3", "1", "0", "-2"):
            with self.subTest(position=value):
                self.setUp()
                self.exchange.captures[1]["position_size"] = value
                self.assertEqual(self.review().status, "hold")

    def test_uncertain_order_without_id_blocks_without_exchange_access(self):
        self.reader.intent["exchange_order_id"] = None
        self.assertEqual(self.review().status, "hold")
        self.assertEqual(self.exchange.order_reads, 0)

    def test_re_read_intent_changed_blocks(self):
        class Changing(RecordedIntentReader):
            def read_intent(self, **kwargs):
                value = super().read_intent(**kwargs)
                if self.intent_reads == 2:
                    value["exchange_order_id"] = "new-order"
                return value
        self.reader = Changing(self.reader.intent, self.reader.baseline)
        self.assertEqual(self.review().status, "hold")

    def test_re_read_pre_submit_capture_changed_blocks(self):
        class Changing(RecordedIntentReader):
            def read_pre_submit_capture(self, **kwargs):
                value = super().read_pre_submit_capture(**kwargs)
                if self.baseline_reads == 2:
                    value["capture_id"] = "another-baseline"
                return value
        self.reader = Changing(self.reader.intent, self.reader.baseline)
        self.assertEqual(self.review().status, "hold")

    def test_second_order_read_mismatch_blocks_handoff(self):
        for field, changed in (
            ("order_id", "wrong-order"),
            ("account", "other-account"),
            ("status", "canceled"),
            ("filled_size", "1"),
            ("final", False),
            ("side", "short"),
        ):
            with self.subTest(field=field):
                self.setUp()
                original = self.exchange.read_order

                def changed_order(**kwargs):
                    result = original(**kwargs)
                    if self.exchange.order_reads == 2:
                        result[field] = changed
                    return result

                self.exchange.read_order = changed_order
                self.assertEqual(self.review().status, "hold")
                self.assertEqual(self.exchange.order_reads, 2)

    def test_second_order_read_error_blocks_handoff(self):
        original = self.exchange.read_order

        def failed_second_read(**kwargs):
            if self.exchange.order_reads == 1:
                raise TimeoutError("exchange unavailable on second read")
            return original(**kwargs)

        self.exchange.read_order = failed_second_read
        self.assertEqual(self.review().status, "hold")

    def test_timeout_fails_closed(self):
        def fail(**kwargs):
            raise TimeoutError("unknown exchange result")
        self.exchange.read_order = fail
        self.assertEqual(self.review().status, "hold")


if __name__ == "__main__":
    unittest.main()
