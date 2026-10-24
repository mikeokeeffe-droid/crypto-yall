"""Read-only metadata audit: does Supabase have backup rows for each live bot?

This does not inspect or export sensitive state and is NOT backup verification.
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
            base + "/rest/v1/bot_state_backups",
            headers=headers,
            params={"select": "revision,backed_up_at", "bot": "eq." + bot,
                    "order": "revision.desc", "limit": "1"},
            timeout=20,
        )
        if response.status_code != 200:
            raise RuntimeError(bot + ": backup metadata query HTTP " + str(response.status_code))
        rows = response.json()
        if not isinstance(rows, list):
            raise RuntimeError(bot + ": invalid backup metadata response")
        if not rows:
            missing.append(bot)
            print(bot + ": NO backup rows found")
        else:
            print(bot + ": backup row exists (revision " + str(rows[0]["revision"]) +
                  ", recorded " + str(rows[0]["backed_up_at"]) + ")")
    if missing:
        print("Missing backup rows for: " + ", ".join(missing), file=sys.stderr)
        raise SystemExit(2)
    print("All bots have backup metadata. Contents and freshness NOT verified.")

if __name__ == "__main__":
    main()
