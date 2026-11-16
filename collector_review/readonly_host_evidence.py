"""Read-only, redacted evidence collection for independent TEST HOST review.

Run only from the already staged, separately designated offline collector host.
No service start/stop/reload, sudo, firewall mutations, networking, credential
readout or exchange access. Only fixed systemctl show/cat + git read commands
are executed; raw unit contents and potentially sensitive outputs are NEVER
printed. Evidence is an operator observation, NOT an independent attestation
or authorization. Manual reviewer must inspect actual host security controls.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UNIT = "testnet-collector-offline-review.service"
PIN = "collector_review/deployment/observed-source-fingerprints-20261115.json"

# Fixed, nonsecret fields only. Never request Environment=, ExecStart=
# or credentials' CONTENTS, and never print systemctl's raw output.
_PROPERTIES = (
    "LoadState", "UnitFileState", "ActiveState", "SubState",
    "Result", "ExecMainStatus",
    "DynamicUser", "NoNewPrivileges", "PrivateNetwork",
    "RestrictAddressFamilies", "IPAddressDeny", "IPAddressAllow",
    "ProtectHome", "ProtectSystem", "PrivateDevices",
    "EnvironmentFiles", "LoadCredential", "LoadCredentialEncrypted",
    "ReadWritePaths", "BindPaths", "BindReadOnlyPaths",
)
_REQUIRED = {
    "LoadState": "loaded",
    "UnitFileState": "static",
    "ActiveState": "inactive",
    "SubState": "dead",
    "Result": "success",
    "ExecMainStatus": "0",
    "DynamicUser": "yes",
    "NoNewPrivileges": "yes",
    "PrivateNetwork": "yes",
    "RestrictAddressFamilies": "AF_UNIX",
    "IPAddressDeny": "any",
    "ProtectHome": "yes",
    "ProtectSystem": "strict",
    "PrivateDevices": "yes",
}
_EMPTY = ("IPAddressAllow", "EnvironmentFiles", "LoadCredential",
          "LoadCredentialEncrypted", "ReadWritePaths", "BindPaths",
          "BindReadOnlyPaths")
_SOURCE_SUFFIXES = frozenset((".py", ".json", ".md", ".example"))


def _run_observation(args, runner):
    """Run only hard-coded read-only commands; suppress raw errors/results."""
    if not (type(args) in (tuple, list) and args
            and args[0] in ("systemctl", "git")):
        return None
    try:
        result = runner(list(args), capture_output=True, text=True,
                        timeout=8, check=False)
        if (result.returncode != 0 or type(result.stdout) is not str
                or len(result.stdout) > 65536):
            return None
        return result.stdout
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return None


def _parse_unit_show(raw):
    if type(raw) is not str or not raw or len(raw) > 8192:
        return None
    fields = {}
    for line in raw.splitlines():
        if "=" not in line:
            return None
        key, value = line.split("=", 1)
        if key not in _PROPERTIES or key in fields:
            return None
        fields[key] = value.strip()
    if set(fields) != set(_PROPERTIES):
        return None
    return fields


def _safe_file_digest(path):
    """Reject symlinks, non-regular and writable-by-others files."""
    fd = None
    try:
        # Hash the opened descriptor, not a path re-opened after lstat:
        # prevents following a substituted source-file symlink.
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        metadata = os.fstat(fd)
        if (not stat.S_ISREG(metadata.st_mode)
                or metadata.st_mode & 0o022
                or not 0 <= metadata.st_size <= 1048576):
            return None
        hasher = hashlib.sha256()
        count = 0
        while count < metadata.st_size:
            data = os.read(fd, min(65536, metadata.st_size - count))
            if not data:
                return None
            hasher.update(data)
            count += len(data)
        # Detect unexpectedly growing files (not just changed metadata).
        if os.read(fd, 1):
            return None
        return hasher.hexdigest()
    except (OSError, ValueError):
        return None
    finally:
        if fd is not None:
            os.close(fd)


def _source_fingerprints(root):
    """Inventory code/docs and compare six older operator-observed hashes.

    Hashes are not cryptographic host attestation or proof that the running
    process executed these files. New files are included in tree aggregate.
    """
    collected = {}
    folder = root / "collector_review"
    try:
        if not folder.is_dir() or folder.is_symlink():
            return None
        for path in sorted(folder.rglob("*")):
            if path.is_symlink():
                return None
            if path.is_file() and path.suffix in _SOURCE_SUFFIXES:
                if len(collected) >= 250:
                    return None
                digest = _safe_file_digest(path)
                if digest is None:
                    return None
                collected[path.relative_to(root).as_posix()] = digest
        pinned = json.loads((root / PIN).read_text(encoding="utf-8"))
        records = pinned["files"]
        valid = (type(records) is list and len(records) == 6
                 and len({r["path"] for r in records}) == 6
                 and all(type(r.get("sha256")) is str
                         and type(r.get("path")) is str for r in records))
        matches = (valid and all(collected.get(r["path"]) == r["sha256"]
                                 for r in records))
        aggregate = hashlib.sha256()
        for name, digest in sorted(collected.items()):
            aggregate.update(name.encode("utf-8") + b"\\0" +
                             digest.encode("ascii") + b"\\n")
        return {
            "file_count": len(collected),
            "tree_sha256": aggregate.hexdigest(),
            "operator_observed_six_match": bool(matches),
        }
    except (OSError, ValueError, TypeError, KeyError):
        return None


def collect_readonly_host_evidence(*, root=ROOT, runner=subprocess.run):
    """Return a redacted candidate packet; NOTHING here can authorize reads."""
    # Unconditionally deny all operational permissions, even when checked.
    packet = {
        "state": "HOLD_EXTERNAL_INDEPENDENT_REVIEW",
        "source_sha": None,
        "source_worktree_clean": False,
        "source_fingerprints": None,
        "effective_unit_sha256": None,
        "unit_fields_observed": False,
        "unit_restrictions_candidate": False,
        "unit_not_running_candidate": False,
        "effective_network_egress_verified": False,
        "secret_absence_independently_verified": False,
        "reviewer_signed_off": False,
        "testnet_network_authorized": False,
        "trading_authorized": False,
    }
    root = Path(root)
    packet["source_fingerprints"] = _source_fingerprints(root)
    sha = _run_observation(("git", "-C", str(root), "rev-parse", "HEAD"), runner)
    if (sha is not None and len(sha.strip()) == 40
            and all(c in "0123456789abcdef" for c in sha.strip())):
        packet["source_sha"] = sha.strip()
    clean = _run_observation(
        ("git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"),
        runner,
    )
    packet["source_worktree_clean"] = clean == ""
    show = _run_observation(
        ("systemctl", "show", UNIT, "--no-pager",
         *("-p" + field for field in _PROPERTIES)), runner,
    )
    fields = _parse_unit_show(show)
    packet["unit_fields_observed"] = fields is not None
    if fields is not None:
        packet["unit_not_running_candidate"] = (
            fields["LoadState"] == "loaded"
            and fields["ActiveState"] == "inactive"
            and fields["UnitFileState"] == "static"
            and fields["SubState"] == "dead"
            and fields["Result"] == "success"
            and fields["ExecMainStatus"] == "0"
        )
        packet["unit_restrictions_candidate"] = (
            all(fields.get(k) == v for k, v in _REQUIRED.items())
            and all(not fields.get(k) for k in _EMPTY)
        )
    unit_text = _run_observation(
        ("systemctl", "cat", UNIT, "--no-pager"), runner,
    )
    if unit_text:
        packet["effective_unit_sha256"] = hashlib.sha256(
            unit_text.encode("utf-8")
        ).hexdigest()
    return packet


def main():
    print(json.dumps(collect_readonly_host_evidence(),
                     sort_keys=True, separators=(",", ":")))
    return 0  # Evidence collection isn't an authorization result.


if __name__ == "__main__":
    raise SystemExit(main())
