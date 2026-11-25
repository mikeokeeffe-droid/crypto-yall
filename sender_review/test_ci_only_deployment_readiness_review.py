"""No-Go deployment manifest negative tests, without service actions."""
from copy import deepcopy
import ast
import json
from pathlib import Path
import unittest

from sender_review.ci_only_deployment_readiness_review import (
    MANIFEST, EXPECTED_IDS, DENIED_FLAGS, inspect_checked_in_readiness,
    review_readiness_bytes,
)


class DeploymentReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads(MANIFEST.read_text("utf-8"))

    def check(self, document):
        return review_readiness_bytes(manifest_bytes=json.dumps(document).encode())

    def test_all_fourteen_gates_unverified_no_go(self):
        result = inspect_checked_in_readiness()
        self.assertTrue(result.manifest_valid)
        self.assertEqual(result.decision, "NO_GO")
        for name in (
            "independent_host_verified", "security_approved",
            "testnet_authorized", "production_authorized",
            "deploy_allowed", "trade_allowed",
        ):
            self.assertFalse(getattr(result, name))
        self.assertEqual(tuple(g["id"] for g in self.source["gates"]), EXPECTED_IDS)

    def test_claiming_deployment_or_ci_approval_fails(self):
        for flag in DENIED_FLAGS:
            doc = deepcopy(self.source)
            doc[flag] = True
            with self.subTest(flag=flag):
                self.assertFalse(self.check(doc).manifest_valid)
                self.assertEqual(self.check(doc).decision, "NO_GO")

    def test_malformed_missing_duplicated_and_spoofed_gates_fail(self):
        mutations = []
        missing = deepcopy(self.source)
        missing["gates"].pop()
        mutations.append(missing)
        duplicate = deepcopy(self.source)
        duplicate["gates"][-1] = deepcopy(duplicate["gates"][0])
        mutations.append(duplicate)
        wrong_owner = deepcopy(self.source)
        wrong_owner["gates"][0]["owner"] = "operator"
        mutations.append(wrong_owner)
        wrong_status = deepcopy(self.source)
        wrong_status["gates"][0]["status"] = "APPROVED"
        mutations.append(wrong_status)
        forged_evidence = deepcopy(self.source)
        forged_evidence["gates"][0]["evidence_reference"] = "fake://evidence"
        mutations.append(forged_evidence)
        forged_reviewer = deepcopy(self.source)
        forged_reviewer["gates"][0]["reviewer"] = "self-approved"
        mutations.append(forged_reviewer)
        forged_sha = deepcopy(self.source)
        forged_sha["gates"][0]["approved_commit"] = "a"*40
        mutations.append(forged_sha)
        extra = deepcopy(self.source)
        extra["gates"][0]["runtime_attested"] = True
        mutations.append(extra)
        wrong_order = deepcopy(self.source)
        wrong_order["gates"][0], wrong_order["gates"][1] = (
            wrong_order["gates"][1], wrong_order["gates"][0]
        )
        mutations.append(wrong_order)
        for doc in mutations:
            with self.subTest(gates=doc["gates"]):
                result = self.check(doc)
                self.assertFalse(result.manifest_valid)
                self.assertFalse(result.deploy_allowed)

    def test_wrong_repo_branch_production_env_and_extra_fields_fail(self):
        variants = {
            "review_pr": 40,
            "repository": "someone/else",
            "review_branch": "main",
            "global_decision": "GO",
            "verified_scope": "production audited",
            "schema_version": True,
        }
        for key, value in variants.items():
            doc = deepcopy(self.source)
            doc[key] = value
            self.assertFalse(self.check(doc).manifest_valid, key)
        doc = deepcopy(self.source)
        doc["override"] = "deploy"
        self.assertFalse(self.check(doc).manifest_valid)

    def test_duplicate_json_keys_unknown_input_and_nonfinite_never_authorize(self):
        for payload in (
            b"",
            b"not-json",
            b'{"global_decision":"NO_GO","global_decision":"GO"}',
            b"{}",
            b"\xff",
            b" " * 65537,
        ):
            result = review_readiness_bytes(manifest_bytes=payload)
            self.assertEqual(result.decision, "NO_GO")
            self.assertFalse(result.manifest_valid)

    def test_only_pure_file_read_stdlib_imports(self):
        path = Path(__file__).with_name(
            "ci_only_deployment_readiness_review.py"
        )
        modules = set()
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add(node.module)
        self.assertEqual(modules, {"dataclasses", "json", "pathlib"})


if __name__ == "__main__":
    unittest.main()
