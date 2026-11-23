"""Build or compare an OFFLINE source inventory for PR #41 collector review.

This tool reads collector_review Python source and the inert systemd example
only. It never imports collector code, reads credentials, accesses the network,
changes systemd, deploys, or grants runtime/testnet/trading authority.

A matching inventory verifies FILE BYTES only; it does not attest the host,
its runtime, dependencies, permissions, service settings, network isolation,
provenance of the supplied inventory, or security approval.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
_MARKER = "PR41_COLLECTOR_SOURCE_INVENTORY_OFFLINE_ONLY"
_TEMPLATE = "deployment/testnet-collector-offline-review.service.example"
_MAX_FILES = 128
_MAX_FILE_BYTES = 512 * 1024


def inventory():
    """Inspect source bytes without executing any inspected collector files."""
    if _ROOT.is_symlink():
        raise ValueError("source root is a symlink")
    found = []
    for path in _ROOT.rglob("*"):
        if path.is_symlink():
            raise ValueError("symlink in collector source: " + str(path))
        if not path.is_file():
            continue
        relative = path.relative_to(_ROOT).as_posix()
        if path.suffix != ".py" and relative != _TEMPLATE:
            continue
        if path.stat().st_size > _MAX_FILE_BYTES:
            raise ValueError("unexpectedly large source file: " + relative)
        data = path.read_bytes()
        found.append({
            "path": relative,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    found.sort(key=lambda item: item["path"])
    paths = [item["path"] for item in found]
    if not (10 <= len(paths) <= _MAX_FILES and _TEMPLATE in paths):
        raise ValueError("missing or unexpected collector source inventory")
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate collector source path")
    return {
        "schema_version": 1,
        "artifact": _MARKER,
        "limitations": "Source bytes only; host, runtime, credentials, network and trade approval UNVERIFIED",
        "testnet_network_authorized": False,
        "trading_authorized": False,
        "files": found,
    }


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    option = parser.add_mutually_exclusive_group(required=True)
    option.add_argument("--emit", type=Path, metavar="JSON_FILE")
    option.add_argument("--verify", type=Path, metavar="JSON_FILE")
    args = parser.parse_args(argv)
    try:
        local = inventory()
        if args.emit:
            # Output goes to an explicitly chosen file, not the source tree by default.
            args.emit.write_text(
                json.dumps(local, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print("Offline source inventory written:", len(local["files"]), "files")
            print("NOT a host attestation; testnet and trading remain NO-GO")
            return 0
        supplied = json.loads(args.verify.read_text(encoding="utf-8"))
        if type(supplied) is not dict or supplied != local:
            print("SOURCE INVENTORY MISMATCH / HOLD", file=sys.stderr)
            # Do not print contents of the supplied file or source paths.
            return 1
        print("SOURCE BYTES MATCH:", len(local["files"]), "files")
        print("NOT a host attestation; testnet and trading remain NO-GO")
        return 0
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        print("SOURCE INVENTORY HOLD:", type(error).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
