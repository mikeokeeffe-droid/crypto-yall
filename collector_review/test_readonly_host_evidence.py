"""Mocked checks: host evidence is redacted and never authorizes anything."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from collector_review.readonly_host_evidence import (
    _PROPERTIES, _REQUIRED, _source_fingerprints,
    collect_readonly_host_evidence,
)


class Result:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode


class EvidenceTests(unittest.TestCase):
    def root(self, path):
        folder = path / "collector_review" / "deployment"
        folder.mkdir(parents=True)
        sources = []
        for i in range(6):
            name = f"collector_review/test_{i}.py"
            data = f"# inert file {i}\n".encode()
            dest = path / name
            dest.write_bytes(data)
            sources.append({"path": name,
                            "sha256": hashlib.sha256(data).hexdigest()})
        (folder / "observed-source-fingerprints-20261115.json").write_text(
            json.dumps({"files": sources}), encoding="utf-8",
        )
        return path

    def fake_runner(self, *, overrides=None):
        settings = {key: "" for key in _PROPERTIES}
        settings.update(_REQUIRED)
        settings["SubState"] = "dead"
        settings["UnitFileState"] = "static"
        settings.update(overrides or {})
        shown = "".join(f"{key}={settings[key]}\n" for key in _PROPERTIES)
        commands = []

        def run(args, *, capture_output, text, timeout, check):
            commands.append(args)
            self.assertTrue(capture_output)
            self.assertTrue(text)
            self.assertFalse(check)
            self.assertEqual(timeout, 8)
            if args[0] == "git" and "rev-parse" in args:
                return Result("a" * 40 + "\n")
            if args[0] == "git":
                return Result("")
            if args[:2] == ["systemctl", "show"]:
                return Result(shown)
            if args[:2] == ["systemctl", "cat"]:
                return Result("[Service]\nPrivateNetwork=yes\n")
            self.fail("unexpected command")
        return run, commands

    def denied_fields(self, packet):
        for flag in (
            "effective_network_egress_verified",
            "secret_absence_independently_verified", "reviewer_signed_off",
            "testnet_network_authorized", "trading_authorized",
        ):
            self.assertIs(packet[flag], False)

    def test_sanitized_observation_is_still_hold(self):
        with tempfile.TemporaryDirectory() as t:
            root = self.root(Path(t))
            run, commands = self.fake_runner()
            record = collect_readonly_host_evidence(root=root, runner=run)
            self.assertEqual(record["state"], "HOLD_EXTERNAL_INDEPENDENT_REVIEW")
            self.assertTrue(record["unit_restrictions_candidate"])
            self.assertTrue(record["unit_not_running_candidate"])
            self.assertTrue(record["source_worktree_clean"])
            self.assertEqual(record["source_sha"], "a" * 40)
            self.assertTrue(record["source_fingerprints"][
                "operator_observed_six_match"])
            self.assertEqual(len(commands), 4)
            output = json.dumps(record)
            self.assertNotIn("ExecStart=", output)
            self.assertNotIn("Environment=", output)
            self.denied_fields(record)

    def test_unsafe_or_missing_properties_never_claim_restricted(self):
        for changes in (
            {"PrivateNetwork": "no"},
            {"RestrictAddressFamilies": "AF_UNIX AF_INET"},
            {"IPAddressDeny": ""},
            {"LoadCredential": "sensitive.location"},
            {"EnvironmentFiles": "/etc/secret"},
            {"ActiveState": "active"},
            {"Result": "exit-code"},
            {"ExecMainStatus": "1"},
        ):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as t:
                root = self.root(Path(t))
                run, commands = self.fake_runner(overrides=changes)
                record = collect_readonly_host_evidence(root=root, runner=run)
                if any(k in changes for k in ("ActiveState", "Result", "ExecMainStatus")):
                    self.assertFalse(record["unit_not_running_candidate"])
                else:
                    self.assertFalse(record["unit_restrictions_candidate"])
                self.denied_fields(record)

    def test_symlink_and_changed_source_are_not_pinned(self):
        with tempfile.TemporaryDirectory() as t:
            root = self.root(Path(t))
            self.assertTrue(_source_fingerprints(root)[
                "operator_observed_six_match"])
            (root / "collector_review/test_0.py").write_text("changed\n")
            self.assertFalse(_source_fingerprints(root)[
                "operator_observed_six_match"])
            target = root / "collector_review/test_0.py"
            target.unlink()
            target.symlink_to(root / "collector_review/test_1.py")
            self.assertIsNone(_source_fingerprints(root))

    def test_source_symlink_and_file_replacement_denied(self):
        with tempfile.TemporaryDirectory() as t:
            root = self.root(Path(t))
            target = root / "collector_review/test_0.py"
            other = root / "collector_review/test_1.py"
            target.unlink()
            target.symlink_to(other)
            self.assertIsNone(_source_fingerprints(root))

    def test_last_unit_failure_is_not_reported_as_stopped_success(self):
        with tempfile.TemporaryDirectory() as t:
            root = self.root(Path(t))
            run, commands = self.fake_runner(overrides={
                "ActiveState": "inactive", "Result": "exit-code",
                "ExecMainStatus": "1",
            })
            record = collect_readonly_host_evidence(root=root, runner=run)
            self.assertFalse(record["unit_not_running_candidate"])
            self.assertTrue(record["unit_restrictions_candidate"])
            self.denied_fields(record)

    def test_observation_errors_fail_closed(self):
        with tempfile.TemporaryDirectory() as t:
            root = self.root(Path(t))
            def fails(*args, **kwargs):
                raise subprocess.TimeoutExpired(args[0], 8)
            packet = collect_readonly_host_evidence(root=root, runner=fails)
            self.assertIsNone(packet["source_sha"])
            self.assertFalse(packet["unit_fields_observed"])
            self.assertFalse(packet["unit_restrictions_candidate"])
            self.denied_fields(packet)


if __name__ == "__main__":
    unittest.main()
