"""In-memory sequence rejection tests; no network or trading authority."""
import unittest
from dataclasses import replace
from collector_review.six_frame_request_contract_offline import (
    FIXTURE_ACCOUNT, plan_synthetic_six_frame_readset_offline,
)
from collector_review.six_frame_sequence_review_offline import (
    UntrustedObservedFrame, inspect_untrusted_six_frame_sequence_offline,
)

START = 1700000000000
END = START + 3600000


def fixture():
    plan = plan_synthetic_six_frame_readset_offline(
        account=FIXTURE_ACCOUNT, start_ms=START, end_ms=END)
    assert len(plan.frames) == 6
    return tuple(UntrustedObservedFrame(
        step=frame.step, method=frame.method, path=frame.path,
        body=frame.body, observed_at_ms=START + i * 1000)
        for i, frame in enumerate(plan.frames))


def review(baseline, **changes):
    data = dict(account=FIXTURE_ACCOUNT, start_ms=START, end_ms=END,
                frames=baseline)
    return inspect_untrusted_six_frame_sequence_offline(**dict(data, **changes))


class SixFrameSequenceReviewTests(unittest.TestCase):
    def assert_no_authority(self, result):
        self.assertEqual(result.state, "HOLD")
        for flag in (
            "network_performed", "origin_authenticated",
            "account_authenticated", "replay_resistant",
            "trustworthy_timestamps", "history_complete",
            "position_ownership_verified", "collection_authorized",
            "order_authorized", "close_authorized", "signing_enabled",
        ):
            self.assertIs(getattr(result, flag), False, flag)

    def test_ordered_fixture_still_hold_and_not_replay_proof(self):
        frames = fixture()
        for records in (frames, frames):  # Replayed fixture must not grant authority.
            result = review(records)
            self.assert_no_authority(result)
            self.assertTrue(result.locally_ordered)
            self.assertEqual(result.frames_reviewed, 6)

    def test_reorder_duplicate_missing_and_extra_frames_hold(self):
        frames = fixture()
        cases = (
            frames[1:2] + frames[0:1] + frames[2:],
            frames[:1] + frames[:1] + frames[2:],
            frames[:5],
            frames + frames[-1:],
            list(frames),
            None,
            (),
        )
        for records in cases:
            with self.subTest(records=str(records)[:40]):
                result = review(records)
                self.assert_no_authority(result)
                self.assertFalse(result.locally_ordered)

    def test_wrong_account_timestamps_and_window_hold(self):
        frames = fixture()
        cases = (
            dict(account="0x" + "2" * 40),
            dict(start_ms=END, end_ms=START),
            dict(frames=frames[:1] + (replace(
                frames[1], observed_at_ms=frames[0].observed_at_ms),) + frames[2:]),
            dict(frames=frames[:2] + (replace(
                frames[2], observed_at_ms=frames[0].observed_at_ms),) + frames[3:]),
            dict(frames=tuple(replace(
                record, observed_at_ms=START + idx * 7000)
                for idx, record in enumerate(frames))),
            dict(frames=frames[:1] + (replace(
                frames[1], observed_at_ms=True),) + frames[2:]),
        )
        for changes in cases:
            with self.subTest(changes=str(changes)[:70]):
                result = review(frames, **changes)
                self.assert_no_authority(result)
                self.assertFalse(result.locally_ordered)

    def test_any_tampered_method_route_or_body_hold(self):
        frames = fixture()
        for changes in (
            dict(method="GET"),
            dict(path="/exchange"),
            dict(body=b'{"type":"exchange"}'),
            dict(body=frames[3].body + b" "),
            dict(step=True),
        ):
            records = frames[:3] + (replace(frames[3], **changes),) + frames[4:]
            result = review(records)
            self.assert_no_authority(result)
            self.assertFalse(result.locally_ordered)

    def test_invalid_observation_type_hold(self):
        frames = fixture()
        record = dict(step=1, method="POST", path="/info",
                      body=frames[0].body, observed_at_ms=START)
        self.assertFalse(review((record,) + frames[1:]).locally_ordered)
        self.assert_no_authority(review((record,) + frames[1:]))


if __name__ == "__main__":
    unittest.main()
