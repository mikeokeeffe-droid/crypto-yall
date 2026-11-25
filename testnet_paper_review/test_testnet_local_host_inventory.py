"""No real systemctl calls: test the read-only host inspection contract."""
from types import SimpleNamespace
import unittest

from testnet_paper_review.testnet_local_host_inventory import (
    COLLECTOR, SENDER, read_unit, inspect_local_systemd, LocalHostHold, main
)


def properties(*, loaded=True, active=False, hardening=True):
    return {
        "LoadState":"loaded" if loaded else "not-found",
        "ActiveState":"active" if active else "inactive",
        "SubState":"running" if active else "dead",
        "MainPID":"932" if active else "0",
        "DynamicUser":"yes" if hardening else "no",
        "ProtectHome":"yes",
        "ProtectSystem":"strict",
        "PrivateDevices":"yes",
    }


class LocalInventoryTests(unittest.TestCase):
    def test_inactive_collector_and_absent_sender_review_only(self):
        def get(unit):
            if unit==COLLECTOR:return properties()
            return {**properties(loaded=False),"ActiveState":"inactive"}
        report=inspect_local_systemd(reader=get)
        self.assertTrue(report.offline_collector_inactive)
        self.assertTrue(report.collector_hardening_verified)
        self.assertTrue(report.one_shot_sender_inactive)
        self.assertFalse(report.may_start)
        self.assertFalse(report.may_trade)

    def test_active_services_and_weak_hardening_hold(self):
        cases=(
            {COLLECTOR:properties(active=True),SENDER:properties(loaded=False)},
            {COLLECTOR:properties(hardening=False),SENDER:properties(loaded=False)},
            {COLLECTOR:properties(),SENDER:properties(active=True)},
        )
        for variant in cases:
            with self.subTest(variant=variant),self.assertRaises(LocalHostHold):
                inspect_local_systemd(reader=lambda unit:variant[unit])

    def test_bounded_systemctl_show_fixed_argv(self):
        calls=[]
        def fake(argv,**kwargs):
            calls.append((argv,kwargs))
            output="\n".join(k+"="+v for k,v in properties().items())
            return SimpleNamespace(returncode=0,stdout=output)
        data=read_unit(COLLECTOR,runner=fake)
        self.assertEqual(data["MainPID"],"0")
        args,kwargs=calls[0]
        self.assertEqual(args[:3],["systemctl","show",COLLECTOR])
        self.assertEqual(kwargs["timeout"],5)
        self.assertFalse(kwargs.get("shell",False))
        self.assertNotIn("Environment"," ".join(args))
        for unapproved in ("ssh.service","miner.service","",None):
            with self.assertRaises(LocalHostHold):
                read_unit(unapproved,runner=fake)

    def test_malformed_or_unexpected_read_fails_closed(self):
        for output in ("", "Environment=SECRET", "MainPID=0\nMainPID=0"):
            def fake(*args,**kwargs):
                return SimpleNamespace(returncode=0,stdout=output)
            with self.subTest(output=output),self.assertRaises(LocalHostHold):
                read_unit(COLLECTOR,runner=fake)

    def test_no_arg_does_not_call_systemctl(self):
        self.assertEqual(main([]),2)

if __name__=="__main__":
    unittest.main()
