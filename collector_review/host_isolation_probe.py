"""Host-local, read-only collector sandbox preflight (Linux/systemd only).

Run *inside* a separately reviewed offline systemd sandbox, not on a trading
runner. Reads its own /proc status, cgroup and network namespace identifiers,
and environment variable NAMES (never secret values). No networking, wallet,
exchange SDK, database, order submission or process mutation.

A 'host_candidate' result proves only that certain kernel observations match
a narrow baseline. It does NOT prove external egress policy, file ACLs,
credential absence in mounted files, trusted Hyperliquid provenance, actual
account ownership, or readiness for a real testnet request.
"""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat


_UNIT = "testnet-collector-offline-review.service"
_NETNS = re.compile(r"net:\[[0-9]+\]\Z", re.ASCII)
_CGROUP = re.compile(r"(?:^|/)testnet-collector-offline-review\.service(?:/|$)")
_ALLOWED_ENV = frozenset((
    "HOME", "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "USER", "LOGNAME", "SHELL",
    "INVOCATION_ID", "JOURNAL_STREAM", "SYSTEMD_EXEC_PID",
    "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED",
))
_REQUIRED_CAPS = ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
_HOST_NETNS_REF = Path("/run/collector-review-host/netns")


@dataclass(frozen=True)
class HostProbeDecision:
    state: str = "hold"
    reason: str = "host observations not verified"
    kernel_identity_candidate: bool = False
    privilege_restrictions_candidate: bool = False
    separate_network_namespace_candidate: bool = False
    environment_names_candidate: bool = False
    network_egress_verified: bool = False
    secret_file_access_verified: bool = False
    origin_authenticated: bool = False
    trading_authorized: bool = False
    testnet_read_authorized: bool = False


def _status_fields(source):
    if type(source) is not str or len(source) > 65536:
        return None
    fields = {}
    for line in source.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        if k in fields:
            return None
        fields[k] = v.strip()
    return fields


def review_host_observations_offline(*, status_text, cgroup_text,
                                     process_netns, init_netns,
                                     effective_uid, effective_gid,
                                     environment_names):
    """Review synthetic or proc-derived observations without OS mutation."""
    def hold(why):
        return HostProbeDecision(reason=why)

    if (type(effective_uid) is not int or effective_uid <= 0
            or type(effective_gid) is not int or effective_gid <= 0
            or type(cgroup_text) is not str
            or type(process_netns) is not str
            or type(init_netns) is not str
            or type(environment_names) not in (tuple, list, frozenset)):
        return hold("missing or unsafe host identity metadata")

    fields = _status_fields(status_text)
    if fields is None:
        return hold("missing, oversized or ambiguous /proc status")
    for field, effective in (("Uid", effective_uid), ("Gid", effective_gid)):
        parts = fields.get(field, "").split()
        if (len(parts) != 4 or any(not x.isdecimal() for x in parts)
                or any(int(x) != effective for x in parts)):
            return hold("real, effective, saved or fs credentials do not match")

    if fields.get("NoNewPrivs") != "1" or fields.get("Seccomp") != "2":
        return hold("missing no-new-privileges or seccomp filter")
    for field in _REQUIRED_CAPS:
        value = fields.get(field, "")
        if (not value or len(value) > 32
                or re.fullmatch(r"[0-9A-Fa-f]+", value, re.ASCII) is None
                or int(value, 16) != 0):
            return hold("nonzero or unknown process capability set")

    # A distinct network namespace is necessary evidence for PrivateNetwork,
    # but does NOT prove that all paths to an external network are denied.
    if (_NETNS.fullmatch(process_netns) is None
            or _NETNS.fullmatch(init_netns) is None
            or process_netns == init_netns):
        return hold("private network namespace not independently observed")

    # Require the *actual* process to be in the named example oneshot unit,
    # not merely running a copied Python script from a normal shell.
    if (len(cgroup_text) > 8192 or not any(
            line.startswith("0::") and _CGROUP.search(line[3:])
            for line in cgroup_text.splitlines())):
        return hold("expected systemd service cgroup not observed")

    if (len(environment_names) > 64
            or any(type(name) is not str or name not in _ALLOWED_ENV
                   for name in environment_names)
            or len(environment_names) != len(set(environment_names))):
        return hold("unexpected environment variable name; values not inspected")

    return HostProbeDecision(
        state="host_candidate",
        reason="local process restrictions appear limited; egress, ACLs and "
               "data provenance still unverified",
        kernel_identity_candidate=True,
        privilege_restrictions_candidate=True,
        separate_network_namespace_candidate=True,
        environment_names_candidate=True,
    )



def _read_root_owned_host_netns_reference():
    """Read an operator-captured, root-owned PID-1 netns ID if procfs denies it.

    This must be created independently *on the dedicated offline host* by
    an authorised operator while outside this sandbox. It is a comparison
    baseline, not proof of egress restrictions, host provenance or authority.
    Fail closed on missing, writable, symlinked, malformed or oversized input.
    """
    try:
        for directory in (Path("/run"), _HOST_NETNS_REF.parent):
            s = directory.lstat()
            if (not stat.S_ISDIR(s.st_mode) or s.st_uid != 0
                    or s.st_gid != 0 or s.st_mode & 0o022):
                return None
        fd = os.open(_HOST_NETNS_REF, os.O_RDONLY | os.O_CLOEXEC
                     | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            s = os.fstat(fd)
            if (not stat.S_ISREG(s.st_mode) or s.st_uid != 0
                    or s.st_gid != 0 or s.st_mode & 0o022
                    or s.st_nlink != 1 or not 1 <= s.st_size <= 64):
                return None
            data = os.read(fd, 65)
        finally:
            os.close(fd)
        baseline = data.decode("ascii").strip()
        return baseline if _NETNS.fullmatch(baseline) else None
    except (OSError, UnicodeError, ValueError):
        return None

def probe_current_host_without_network():
    """Read this process's kernel status; never open sockets or read secrets."""
    try:
        status = Path("/proc/self/status").read_text(encoding="utf-8")
        cgroup = Path("/proc/self/cgroup").read_text(encoding="utf-8")
        own = os.readlink("/proc/self/ns/net")
        try:
            init = os.readlink("/proc/1/ns/net")
        except PermissionError:
            # DynamicUser cannot necessarily inspect PID 1's ns symlink.
            # Never replace this with a guessed namespace ID or skip the check.
            init = _read_root_owned_host_netns_reference()
            if init is None:
                return HostProbeDecision(
                    reason="PID 1 netns unreadable; trusted host baseline missing"
                )
        uid = os.geteuid()
        gid = os.getegid()
        names = tuple(os.environ.keys())
    except (OSError, UnicodeError, ValueError):
        return HostProbeDecision(reason="procfs unavailable or unreadable")
    return review_host_observations_offline(
        status_text=status, cgroup_text=cgroup,
        process_netns=own, init_netns=init,
        effective_uid=uid, effective_gid=gid,
        environment_names=names,
    )


def _unexpected_environment_name_fingerprints(names):
    """Bounded diagnostic: never print environment names or their values.

    Each truncated hash may be matched against a reviewer-provided shortlist
    of ordinary environment names. Do not treat these hashes as secrets or
    as proof that no credential-bearing names exist.
    """
    unknown = sorted(name for name in names
                     if type(name) is str and name not in _ALLOWED_ENV)
    tokens = tuple(hashlib.sha256(
        ("offline-collector-env-v1:" + name).encode("utf-8")
    ).hexdigest()[:16] for name in unknown[:8])
    return len(unknown), tokens


def main():
    # Deliberately print no UID, environment name/value, process argv,
    # account address, credential, network endpoint, or procfs content.
    result = probe_current_host_without_network()
    print("collector_host_probe=" + result.state)
    print("collector_host_probe_detail=" + result.reason)
    if (result.state == "hold" and result.reason ==
            "unexpected environment variable name; values not inspected"):
        count, fingerprints = _unexpected_environment_name_fingerprints(
            tuple(os.environ.keys()))
        print("collector_unapproved_env_name_count=" + str(count))
        print("collector_unapproved_env_name_fingerprints=" +
              ",".join(fingerprints))
    print("network_egress_verified=false")
    print("testnet_read_authorized=false")
    print("trading_authorized=false")
    return 0 if result.state == "host_candidate" else 1


if __name__ == "__main__":
    raise SystemExit(main())
