"""Offline request-plan checks. No host commands are executed."""
import ast
from pathlib import Path
import unittest

from sender_review.host_evidence_request_offline import (
    SERVICE_NAME, make_host_evidence_request_offline,
)

class HostEvidenceRequestTests(unittest.TestCase):
    def test_request_has_no_verified_evidence_or_authority(self):
        r=make_host_evidence_request_offline()
        self.assertEqual(r.status,"NO_GO_UNATTESTED")
        self.assertEqual(r.target_service,SERVICE_NAME)
        self.assertEqual(len(r.evidence),10)
        for field in ("verified_on_actual_host","independent_security_approval",
                      "testnet_network_approval","live_trading_approval",
                      "safe_to_deploy","safe_to_trade"):
            self.assertFalse(getattr(r,field))
        for item in r.evidence:
            self.assertEqual(item.assessment,"NOT_COLLECTED")
            self.assertFalse(item.reviewer_verified)
            self.assertFalse(item.approved_for_deployment)

    def test_only_fixed_allowlisted_read_only_queries(self):
        r=make_host_evidence_request_offline()
        commands=[x.read_only_command for x in r.evidence if x.read_only_command]
        self.assertEqual(len(commands),2)
        self.assertTrue(commands[0].startswith("systemctl show "+SERVICE_NAME+" "))
        self.assertTrue(commands[1].startswith("systemd-analyze security --no-pager "+SERVICE_NAME))
        for command in commands:
            for unsafe in ("Environment=","EnvironmentFile","LoadCredential",
                           "ExecStart","cat ","journalctl","sudo ","--user",
                           "systemctl start","systemctl enable","systemctl restart",
                           "systemctl edit","bash -c", ";","|","&&","\n"):
                with self.subTest(command=command,unsafe=unsafe):
                    self.assertNotIn(unsafe,command)

    def test_manual_evidence_never_claimed_collected(self):
        r=make_host_evidence_request_offline()
        self.assertEqual(len({x.id for x in r.evidence}),len(r.evidence))
        for item in r.evidence:
            self.assertGreater(len(item.purpose),30)
        self.assertIsNone(r.evidence[0].read_only_command)
        self.assertIsNone(r.evidence[-1].read_only_command)

    def test_module_cannot_execute_host_inspection(self):
        source=Path(__file__).with_name("host_evidence_request_offline.py").read_text("utf-8")
        tree=ast.parse(source)
        modules=set()
        for n in ast.walk(tree):
            if isinstance(n,ast.Import):
                modules.update(x.name for x in n.names)
            elif isinstance(n,ast.ImportFrom):
                modules.add(n.module)
            elif isinstance(n,ast.Call):
                name=n.func.id if isinstance(n.func,ast.Name) else (
                    n.func.attr if isinstance(n.func,ast.Attribute) else "")
                self.assertNotIn(name, {
                    "system", "popen", "run", "Popen", "check_output",
                    "connect", "urlopen", "request", "exec", "eval",
                    "__import__", "subprocess",
                })
        self.assertEqual(modules,{"dataclasses"})

if __name__ == "__main__":
    unittest.main()
