"""Offline verification of a source JSON file against an exported backup JSON file.

Usage: python scripts/verify_state_backup.py SOURCE.json BACKUP.json
Never connects to exchanges or modifies any files.
"""
import hashlib
import json
import sys
from pathlib import Path

def canonical(value):
    if not isinstance(value, dict):
        raise ValueError("Trading state must be a JSON object")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

def verify(source, backup):
    original = canonical(json.loads(Path(source).read_text(encoding="utf-8")))
    restored = canonical(json.loads(Path(backup).read_text(encoding="utf-8")))
    if original != restored:
        raise ValueError("Source and backup differ")
    return hashlib.sha256(original).hexdigest()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: verify_state_backup.py SOURCE.json BACKUP.json")
    print("Verified identical JSON state; sha256=" + verify(sys.argv[1], sys.argv[2]))
