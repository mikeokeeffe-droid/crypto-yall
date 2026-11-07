"""Offline-only crash/restart policy; does not start processes or call APIs.

The server is not allowed to resume a trading-capable state after a crash.
Operator must run fresh offline preflight, independently reconcile any
in-flight orders, and explicitly approve any later production transition.
"""
from dataclasses import dataclass, field
from server_staging_control import OfflineServerControl, Mode


@dataclass
class OfflineCrashRecovery:
    control: OfflineServerControl = field(default_factory=OfflineServerControl)
    unknown_order_intents: set = field(default_factory=set)
    crashed: bool = False

    def observe_unknown_intent(self, intent_id):
        if not isinstance(intent_id, str) or not intent_id.strip():
            raise ValueError("intent ID required")
        self.unknown_order_intents.add(intent_id)

    def crash(self):
        self.control.stop()
        self.crashed = True
        return self.status()

    def restart_offline(self, env):
        if self.unknown_order_intents:
            raise RuntimeError("unreconciled order intents: startup remains blocked")
        status = self.control.start(env)
        self.crashed = False
        return status

    def confirm_reconciled(self, intent_id, *, authoritative_order_final, authoritative_position_flat):
        if intent_id not in self.unknown_order_intents:
            return False
        if authoritative_order_final is not True or authoritative_position_flat is not True:
            return False
        self.unknown_order_intents.remove(intent_id)
        return True

    def status(self):
        return {
            "mode": self.control.mode.value,
            "crashed": self.crashed,
            "unreconciled_intent_count": len(self.unknown_order_intents),
            "order_capable_processes_started": 0,
        }
