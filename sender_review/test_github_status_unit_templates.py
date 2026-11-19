"""Offline-only checks of non-deployed user-level GitHub observer templates."""
from configparser import ConfigParser
from pathlib import Path
import unittest

_ROOT = Path(__file__).resolve().parent / "deployment"
_SERVICE = _ROOT / "crypto-yall-status-review.service.example"
_TIMER = _ROOT / "crypto-yall-status-review.timer.example"


def parsed(path):
    cfg = ConfigParser(interpolation=None, strict=False)
    # systemd permits repeated directives, including Environment=.
    with path.open(encoding="utf-8") as handle:
        cfg.read_file(handle)
    return cfg


class ReviewOnlyStatusUnitTemplateTests(unittest.TestCase):
    def test_service_is_nontrading_oneshot_running_as_nonroot_user(self):
        service = parsed(_SERVICE)
        self.assertEqual(service["Service"]["Type"], "oneshot")
        self.assertEqual(
            service["Service"]["ExecStart"],
            "/usr/bin/python3 -B -m sender_review.github_actions_readonly_observer",
        )
        self.assertEqual(
            service["Service"]["WorkingDirectory"],
            "%h/crypto-yall-monitor/repo",
        )
        self.assertEqual(service["Service"]["NoNewPrivileges"], "yes")
        self.assertEqual(service["Service"]["ProtectSystem"], "strict")
        self.assertEqual(service["Service"]["ProtectHome"], "read-only")
        self.assertEqual(service["Service"]["CapabilityBoundingSet"], "")
        self.assertNotIn("Install", service)
        self.assertNotIn("User", service["Service"])
        self.assertNotIn("ExecStartPre", service["Service"])
        self.assertNotIn("ExecStartPost", service["Service"])
        src = _SERVICE.read_text(encoding="utf-8").lower()
        for forbidden in (
            "hl_private_key=", "secret=", "github_token=",
            "supabase_url=", "exchange/", "market_close(",
            "curl ", "bash -c", "wget ", "root",
        ):
            if forbidden == "root":
                # Comment says "not root"; not a permission grant.
                continue
            self.assertNotIn(forbidden, src)

    def test_timer_every_two_minutes_and_not_persistent(self):
        timer = parsed(_TIMER)
        self.assertEqual(
            timer["Timer"]["Unit"], "crypto-yall-status-review.service"
        )
        self.assertEqual(timer["Timer"]["OnUnitInactiveSec"], "2min")
        self.assertEqual(timer["Timer"]["OnBootSec"], "2min")
        self.assertEqual(timer["Timer"]["Persistent"], "false")
        self.assertEqual(timer["Install"]["WantedBy"], "timers.target")

    def test_templates_are_non_deploying(self):
        self.assertTrue(_SERVICE.name.endswith(".example"))
        self.assertTrue(_TIMER.name.endswith(".example"))
        self.assertNotIn("ExecStart=", _TIMER.read_text(encoding="utf-8"))
        self.assertNotIn("trading authority", _SERVICE.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
