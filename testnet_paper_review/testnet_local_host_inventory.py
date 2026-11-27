"""Local Ubuntu systemd read-only safety inventory for offline Testnet host.

This is NOT a deployment, installation or trading control.
It only calls systemctl show on two hard-coded units. No sudo, no shell,
service lifecycle commands, file reads, wallet keys, env variables, network,
DB initialization or orders. Output excludes ExecStart/Environment values.

Run on the actual dedicated Ubuntu host with --read-only-check, never via
GitHub Actions as proof of that host's state. Absence of these two units
does not prove all other possible trading processes are inactive.
"""
import argparse
from dataclasses import dataclass, asdict
import json
import subprocess
import sys

COLLECTOR = "testnet-collector-offline-review.service"
SENDER = "testnet-one-shot-sender.service"
PROPS = ("LoadState", "ActiveState", "SubState", "MainPID",
         "DynamicUser", "ProtectHome", "ProtectSystem", "PrivateDevices")
MAX_OUTPUT_BYTES = 4096


class LocalHostHold(RuntimeError):
    pass


@dataclass(frozen=True)
class HostServiceInventory:
    offline_collector_inactive: bool
    collector_hardening_verified: bool
    one_shot_sender_inactive: bool
    status: str = "LOCAL_HOST_READ_ONLY_HOLD"

    @property
    def may_start(self):
        return False

    @property
    def may_trade(self):
        return False


def read_unit(unit, *, runner=subprocess.run):
    """Bounded, fixed-argv systemctl show. Never prints unit config or secrets."""
    if unit not in (COLLECTOR, SENDER):
        raise LocalHostHold("HOLD: unexpected systemd unit")
    argv = ["systemctl", "show", unit,
            "--property=" + ",".join(PROPS), "--no-pager"]
    try:
        proc = runner(argv, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LocalHostHold("HOLD: cannot read local systemd state") from exc
    if (proc.returncode != 0 or type(proc.stdout) is not str
            or len(proc.stdout.encode("utf-8")) > MAX_OUTPUT_BYTES):
        raise LocalHostHold("HOLD: invalid local systemd response")
    items={}
    for line in proc.stdout.splitlines():
        if "=" not in line:
            raise LocalHostHold("HOLD: malformed systemd property")
        k,v = line.split("=",1)
        if k not in PROPS or k in items or len(v) > 200:
            raise LocalHostHold("HOLD: unknown/repeated systemd property")
        items[k]=v
    if set(items) != set(PROPS):
        raise LocalHostHold("HOLD: incomplete local systemd evidence")
    return items


def inspect_local_systemd(*, reader=read_unit):
    collector=reader(COLLECTOR)
    sender=reader(SENDER)
    if (collector["LoadState"] != "loaded"
            or collector["ActiveState"] != "inactive"
            or collector["SubState"] != "dead"
            or collector["MainPID"] != "0"):
        raise LocalHostHold("HOLD: offline collector not proven inactive")
    # Hardening protects the dormant review service. It does NOT authorize a
    # trading service or establish host-wide network egress restrictions.
    hardened = (collector["DynamicUser"] == "yes"
                and collector["ProtectHome"] in ("yes", "read-only", "tmpfs")
                and collector["ProtectSystem"] == "strict"
                and collector["PrivateDevices"] == "yes")
    if not hardened:
        raise LocalHostHold("HOLD: collector review-service hardening not verified")
    if sender["LoadState"] == "not-found":
        # A service not installed is expected and safe for this stage.
        if sender["ActiveState"] not in ("inactive","failed") \
                or sender["MainPID"] != "0":
            raise LocalHostHold("HOLD: unexpected absent sender state")
    elif (sender["LoadState"] != "loaded"
          or sender["ActiveState"] != "inactive"
          or sender["SubState"] != "dead"
          or sender["MainPID"] != "0"):
        raise LocalHostHold("HOLD: one-shot sender may be active")
    return HostServiceInventory(
        offline_collector_inactive=True,
        collector_hardening_verified=True,
        one_shot_sender_inactive=True,
    )


def main(argv=None):
    parser=argparse.ArgumentParser(description="Read local Ubuntu systemd state; NO TRADES")
    parser.add_argument("--read-only-check", action="store_true")
    args=parser.parse_args(argv)
    if not args.read_only_check:
        print("HOLD: explicit read-only flag required", file=sys.stderr)
        return 2
    try:
        result=inspect_local_systemd()
    except LocalHostHold as exc:
        print(str(exc),file=sys.stderr)
        return 2
    print(json.dumps(asdict(result),sort_keys=True))
    print("HOLD: no services started; no wallet or live sender verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
