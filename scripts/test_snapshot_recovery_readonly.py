"""Read-only recovery drill: fetch each verified snapshot, reconstruct canonical JSON in memory, and verify its stored SHA-256. Never writes to Supabase, GitHub Gists, or the exchange."""
import hashlib
import json
import os
import requests

BOTS = ("aggressive", "intraday", "daily")

def canonical(value):
    if not isinstance(value, dict):
        raise ValueError("Snapshot state must be an object")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

def validate_row(bot, row):
    if row.get("bot") != bot or row.get("verified") is not True:
        raise ValueError(bot + ": wrong bot or unverified snapshot")
    expected = row.get("source_sha256", "")
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError(bot + ": invalid stored digest")
    restored_bytes = canonical(row["state"])
    actual = hashlib.sha256(restored_bytes).hexdigest()
    if actual != expected:
        raise ValueError(bot + ": reconstructed state digest mismatch")
    return len(restored_bytes)

def main():
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key
    for bot in BOTS:
        response = requests.get(
            base + "/rest/v1/bot_state_snapshots",
            headers=headers,
            params={
                "bot": "eq." + bot,
                "verified": "eq.true",
                "select": "bot,verified,state,source_sha256,snapshot_id,captured_at",
                "order": "captured_at.desc",
                "limit": "1",
            },
            timeout=30,
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or len(rows) != 1:
            raise RuntimeError(bot + ": no verified snapshot available")
        size = validate_row(bot, rows[0])
        print(bot + ": read-only recovery validated (" + str(size) + " JSON bytes)")
    print("PASS: three snapshots reconstructed and checksummed in memory; no writes performed")

if __name__ == "__main__":
    main()
