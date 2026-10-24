"""Read-only check of state backups and verified recovery snapshots.

No database mutations or exchange calls. Does not perform a restoration.
"""
import os
import sys
import requests

BOTS = {"aggressive", "intraday", "daily"}


def main():
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key
    def read(table, params):
        response = requests.get(url + table, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError("Unexpected API response")
        return rows

    states = read("bot_state", {"select": "bot,revision", "limit": "10"})
    snapshots = read("bot_state_snapshots", {
        "select": "bot,snapshot_id,verified", "verified": "eq.true", "limit": "1000"
    })
    backups = read("bot_state_backups", {
        "select": "bot,revision", "limit": "1000"
    })
    state_map = {r["bot"]: r for r in states}
    if len(states) != 3 or set(state_map) != BOTS:
        raise RuntimeError("Missing or unexpected bot_state rows")
    verified = {r["bot"] for r in snapshots if r["verified"] is True}
    if not BOTS.issubset(verified):
        raise RuntimeError("Missing verified recovery snapshot")
    for bot in sorted(BOTS):
        revision = state_map[bot]["revision"]
        if type(revision) is not int or revision < 1:
            raise RuntimeError("Invalid revision for " + bot)
        historical = [r for r in backups if r["bot"] == bot]
        if revision > 1 and not historical:
            raise RuntimeError("Missing previous-state backup for " + bot)
        print("PASS", bot, "revision", revision, "verified snapshot exists",
              "backup rows", len(historical))
    print("READ-ONLY RECOVERY COVERAGE PASSED. No restoration attempted.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("FAIL: " + str(exc), file=sys.stderr)
        sys.exit(1)
