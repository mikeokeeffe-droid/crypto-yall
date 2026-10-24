"""Read-only verification of initialized Supabase state against three pinned snapshots."""
import os
import sys
import requests

SNAPSHOTS = {
    "aggressive": "a1b15195-0014-4863-a0a5-6ca206bc1a3c",
    "intraday": "77fab103-c658-42d3-aaf8-22ea97585e91",
    "daily": "5f81de3d-3fec-4dec-a386-aac430690819",
}

def main():
    base = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key
    session = requests.Session()
    def read(table, params):
        response = session.get(base + table, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, list):
            raise ValueError("Unexpected API response")
        return result

    states = read("bot_state", {"select":"bot,revision,state", "limit":"10"})
    snapshots = read("bot_state_snapshots", {
        "select":"bot,snapshot_id,state,verified,verified_at",
        "snapshot_id":"in.(" + ",".join(SNAPSHOTS.values()) + ")",
        "limit":"10"
    })
    if len(states) != 3 or len(snapshots) != 3:
        raise ValueError("Expected exactly three states and three pinned snapshots")
    state_map = {row["bot"]: row for row in states}
    snap_map = {row["bot"]: row for row in snapshots}
    if set(state_map) != set(SNAPSHOTS) or set(snap_map) != set(SNAPSHOTS):
        raise ValueError("Unexpected or missing bot")
    for bot, snapshot_id in SNAPSHOTS.items():
        row, snap = state_map[bot], snap_map[bot]
        if row["revision"] != 1 or snap["snapshot_id"] != snapshot_id or snap["verified"] is not True or not snap["verified_at"] or row["state"] != snap["state"]:
            raise ValueError("State mismatch for " + bot)
        print("PASS " + bot + ": revision 1, exact verified snapshot match")
    print("READ-ONLY API STATE VERIFICATION PASSED; no writes performed")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("FAIL: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        sys.exit(1)
