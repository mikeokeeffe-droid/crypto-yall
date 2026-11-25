"""OFFLINE REVIEW of Linux process provenance, not process authentication.

Reads only local /proc process metadata. No sockets, HTTP, SSH, gateway,
privilege changes, deployment or trading access. It does not bind an approved
service to a kernel process or supply a complete anti-TOCTOU security boundary.
An independent reviewer must verify that the gateway uses the actual kernel
SO_PEERCRED PID and keeps an appropriate pidfd or equivalent OS binding.
"""
import os
from collections import namedtuple
from pathlib import Path

from readonly_connection_review.testnet_egress_policy_review_offline import PolicyHold

ProcessProvenance = namedtuple(
    "ProcessProvenance", "pid start_ticks cgroup_v2 executable"
)


def parse_proc_stat_start_ticks(contents, pid):
    """Parse Linux /proc/PID/stat field 22 despite spaces/parentheses in comm."""
    if type(pid) is not int or pid <= 1 or not isinstance(contents, str):
        raise PolicyHold("invalid process stat fixture")
    prefix = str(pid) + " ("
    if not contents.startswith(prefix):
        raise PolicyHold("wrong stat pid")
    marker = contents.rfind(") ")
    if marker <= len(prefix):
        raise PolicyHold("malformed process stat")
    rest = contents[marker + 2:].split()
    # After comm, field 3 is index 0; starttime is field 22, index 19.
    if len(rest) < 20 or len(rest[0]) != 1:
        raise PolicyHold("incomplete process stat")
    try:
        ticks = int(rest[19])
    except (ValueError, TypeError):
        raise PolicyHold("malformed start ticks") from None
    if ticks <= 0:
        raise PolicyHold("invalid start ticks")
    return ticks


def parse_cgroup_v2(contents):
    """Fail closed if unified cgroup membership is absent or ambiguous."""
    if not isinstance(contents, str):
        raise PolicyHold("invalid cgroup fixture")
    lines = [line for line in contents.splitlines() if line]
    if len(lines) != 1 or not lines[0].startswith("0::"):
        raise PolicyHold("unique cgroup v2 membership required")
    path = lines[0][3:]
    if (not path.startswith("/") or "\x00" in path or
            ".." in path.split("/") or len(path) > 4096):
        raise PolicyHold("invalid cgroup v2 path")
    return path


def read_linux_process_provenance(pid):
    """Collect read-only /proc data for a kernel-derived PID, with a race check.

    Important: a second stat read only *detects some* PID reuse races. It is
    NOT sufficient to authenticate a process, especially across namespaces.
    """
    if type(pid) is not int or pid <= 1:
        raise PolicyHold("invalid process pid")
    base = Path("/proc") / str(pid)
    try:
        start_stat = (base / "stat").read_text(encoding="utf-8")
        ticks = parse_proc_stat_start_ticks(start_stat, pid)
        cgroup = parse_cgroup_v2((base / "cgroup").read_text(encoding="utf-8"))
        exe = os.readlink(base / "exe")
        final_stat = (base / "stat").read_text(encoding="utf-8")
        if parse_proc_stat_start_ticks(final_stat, pid) != ticks:
            raise PolicyHold("process changed while being reviewed")
    except (OSError, UnicodeError):
        raise PolicyHold("process provenance unavailable") from None
    if not exe.startswith("/") or exe.endswith(" (deleted)") or "\x00" in exe:
        raise PolicyHold("executable unavailable")
    return ProcessProvenance(pid, ticks, cgroup, exe)


def matches_reviewed_process(actual, expected):
    """Compare *synthetic/reviewer-provided* metadata exactly. No authority."""
    if (type(actual) is not ProcessProvenance or
            type(expected) is not ProcessProvenance or
            not all(type(x.pid) is int and x.pid > 1 and
                    type(x.start_ticks) is int and x.start_ticks > 0 and
                    type(x.cgroup_v2) is str and x.cgroup_v2.startswith("/") and
                    type(x.executable) is str and x.executable.startswith("/")
                    for x in (actual, expected)) or
            actual != expected):
        raise PolicyHold("process provenance does not match review fixture")
    return True
