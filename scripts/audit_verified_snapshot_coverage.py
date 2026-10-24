"""Read-only coverage of independently verified Gist snapshots.

A passing result proves metadata presence, not current-source fidelity.
"""
import os
import sys
import requests

BOTS = ("aggressive", "intraday", "daily")


def main():
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key
    missing = []
    for bot in BOTS:
        response = requests.get(
            base + "/rest/v1/bot_state_snapshots",
            headers=headers,
            params={"select": "snapshot_id,captured_at,verified_at",
                    "bot": "eq." + bot, "verified": "eq.true",
                    "order": "captured_at.desc", "limit": "1"},
            timeout=20,
        )
        if response.status_code != 200:
            raise RuntimeError(bot + ": snapshot metadata unavailable, HTTP " + str(response.status_code))
        rows = response.json()
        if not isinstance(rows, list):
            raise RuntimeError(bot + ": invalid response")
        if not rows:
            missing.append(bot)
            print(bot + ": NO verified snapshot")
        else:
            print(bot + ": verified snapshot metadata exists; captured=" +
                  str(rows[0]["captured_at"]) + ", verified=" + str(rows[0]["verified_at"]))
    if missing:
        print("Missing verified snapshots: " + ", ".join(missing), file=sys.stderr)
        sys.exit(2)
    print("All three have verified snapshot metadata; compare with current Gists before cutover.")


if __name__ == "__main__":
    main()
