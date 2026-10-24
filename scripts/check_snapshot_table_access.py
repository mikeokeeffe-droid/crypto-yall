"""Read-only Supabase snapshot table access check. Does not fetch state JSON."""
import os
import requests


def main():
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key
    response = requests.get(
        base + "/rest/v1/bot_state_snapshots",
        headers=headers,
        params={"select": "snapshot_id,bot,verified", "limit": "1"},
        timeout=20,
    )
    if response.status_code != 200:
        raise RuntimeError("Snapshot table access check failed: HTTP " + str(response.status_code))
    if not isinstance(response.json(), list):
        raise RuntimeError("Unexpected snapshot table response")
    print("PASS: GitHub can read snapshot metadata through Supabase.")
    print("No trading state was read, written or changed.")


if __name__ == "__main__":
    main()
