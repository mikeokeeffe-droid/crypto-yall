"""Offline source-pinning check for six independently observed host fingerprints.

The fingerprints came from operator-supplied terminal screenshots. Matching
bytes confirms file identity ONLY, not a signed host attestation, completeness
of a deployment, independent security approval, or exchange access.
No host, socket, subprocess, signer, or network operations occur here.
"""
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).with_name("deployment") / "observed-source-fingerprints-20261115.json"
EXPECTED_PATHS = (
    "collector_review/host_isolation_probe.py",
    "collector_review/ip_socket_denial_probe.py",
    "collector_review/testnet_info_https.py",
    "collector_review/test_testnet_info_https.py",
    "collector_review/offline_capture_audit.py",
    "collector_review/runtime_identity_review.py",
)
EXPECTED_COMMIT = "51957b22c7034ff29d9befbda881ad31574d46c8"


class SourceFingerprintPinTests(unittest.TestCase):
    def test_operator_observed_hashes_match_exact_git_source_bytes(self):
        record = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(record["source_pull_request"], 41)
        self.assertEqual(record["source_commit"], EXPECTED_COMMIT)
        self.assertEqual(record["comparison"], "SIX_OF_SIX_SHA256_MATCH")
        self.assertEqual(record["record_type"], "OPERATOR_SCREENSHOT_TO_GITHUB_SOURCE_HASH_COMPARISON")
        self.assertEqual(record["captured_date_utc"], "2026-11-15")
        for flag in (
            "host_attested", "effective_sandbox_attested",
            "real_exchange_data_authenticated", "testnet_network_authorized",
            "trading_authorized",
        ):
            self.assertIs(record[flag], False)
        records = record["files"]
        self.assertEqual(tuple(item["path"] for item in records), EXPECTED_PATHS)
        for item in records:
            with self.subTest(path=item["path"]):
                self.assertEqual(item["match"], "EXACT")
                self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
                source = (ROOT / item["path"]).read_bytes()
                self.assertEqual(hashlib.sha256(source).hexdigest(), item["sha256"])

    def test_source_identity_is_not_runtime_authorization(self):
        record = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertIn("no signed host attestation", record["observation_limitations"])
        self.assertFalse(record["testnet_network_authorized"])
        self.assertFalse(record["trading_authorized"])


if __name__ == "__main__":
    unittest.main()
