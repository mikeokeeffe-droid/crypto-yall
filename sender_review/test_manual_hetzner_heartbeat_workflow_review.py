"""Offline checks of manually dispatched, non-trading SSH heartbeat workflow."""
from pathlib import Path
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "manual-hetzner-ssh-heartbeat-review.yml"


class ManualHeartbeatWorkflowReviewTests(unittest.TestCase):
    def setUp(self):
        self.src = WORKFLOW.read_text(encoding="utf-8")

    def test_only_manual_default_branch_and_explicit_confirmation(self):
        self.assertIn("  workflow_dispatch:", self.src)
        self.assertNotIn("  pull_request:", self.src)
        self.assertNotIn("  push:", self.src)
        self.assertNotIn("  schedule:", self.src)
        self.assertIn("github.ref == 'refs/heads/main'", self.src)
        self.assertIn("inputs.confirm == 'RUN_READONLY_HEARTBEAT'", self.src)
        self.assertIn("timeout-minutes: 2", self.src)

    def test_read_only_and_secrets_only_for_probe(self):
        self.assertIn("permissions:\n  contents: read", self.src)
        self.assertIn("persist-credentials: false", self.src)
        self.assertIn("HETZNER_HEARTBEAT_SSH_KEY: ${{ secrets.HETZNER_HEARTBEAT_SSH_KEY }}", self.src)
        self.assertIn("HETZNER_HEARTBEAT_HOST_KEY_ED25519: ${{ secrets.HETZNER_HEARTBEAT_HOST_KEY_ED25519 }}", self.src)
        self.assertNotIn("HL_PRIVATE_KEY", self.src)
        self.assertNotIn("execute-trades", self.src)
        self.assertNotIn("curl ", self.src)
        self.assertNotIn("ssh-keyscan", self.src)


if __name__ == "__main__":
    unittest.main()
