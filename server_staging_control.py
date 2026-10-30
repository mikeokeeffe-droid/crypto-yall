"""Offline-only state-machine for proposed server start/stop control.

No processes, sockets, network calls, or real executor imports. This models
operator commands without launching bots or changing any live service.
"""
from dataclasses import dataclass
from enum import Enum
from server_staging_guard import validate_offline_startup

BOTS = frozenset(("daily", "intraday", "aggressive"))


class Mode(Enum):
    STOPPED = "stopped"
    OFFLINE_PREFLIGHT = "offline_preflight"


@dataclass
class OfflineServerControl:
    mode: Mode = Mode.STOPPED
    enabled_bots: frozenset = frozenset()

    def start(self, env, bots=BOTS):
        if self.mode != Mode.STOPPED:
            raise RuntimeError("already started: stop before reconfiguration")
        selected = frozenset(bots)
        if not selected or not selected.issubset(BOTS):
            raise ValueError("only known bot identities are allowed")
        validate_offline_startup(env)
        self.enabled_bots = selected
        self.mode = Mode.OFFLINE_PREFLIGHT
        return self.status()

    def stop(self):
        self.mode = Mode.STOPPED
        self.enabled_bots = frozenset()
        return self.status()

    def status(self):
        return {
            "mode": self.mode.value,
            "bot_identities": sorted(self.enabled_bots),
            "order_capable_processes_started": 0,
        }
