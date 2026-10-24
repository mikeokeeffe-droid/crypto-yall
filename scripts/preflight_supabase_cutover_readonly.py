"""Read-only Supabase cutover preflight. Does not update state or call the exchange."""
import os
import sys
import requests

BOTS = ("aggressive", "intraday", "daily")

def get(base, headers, table, params):
    r = requests.get(base + "/rest/v1/" + table, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    rows = r.json()
    if not isinstance(rows, list):
        raise ValueError("Unexpected Supabase response")
    return rows

def main():
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key

    snapshots = get(base, headers, "bot_state_snapshots", {
        "select": "bot,snapshot_id,verified,source_sha256", "verified": "eq.true", "limit": "1000"
    })
    backed_up = {r["bot"] for r in snapshots if r.get("verified") is True}
    if not set(BOTS).issubset(backed_up):
        raise RuntimeError("Missing verified snapshot for: " + ",".join(set(BOTS)-backed_up))
    print("PASS: verified snapshot exists for each bot")

    states = get(base, headers, "bot_state", {
        "select": "bot,revision", "limit": "1000"
    })
    seen = {}
    for row in states:
        bot = row.get("bot")
        if bot in BOTS:
            if bot in seen:
                raise RuntimeError("Duplicate bot_state row: " + bot)
            revision = row.get("revision")
            if type(revision) is not int or revision < 0:
                raise RuntimeError("Invalid revision for: " + bot)
            seen[bot] = revision
    missing = set(BOTS) - set(seen)
    if missing:
        print("NOT READY: bot_state has no row for: " + ",".join(sorted(missing)))
        print("This is expected before state initialization. No changes made.")
    else:
        print("PASS: all three bot_state rows have valid revision fields")
    print("READ-ONLY PREFLIGHT COMPLETE. This does not validate RPC, writer locking, or live cutover.")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Preflight failed: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
