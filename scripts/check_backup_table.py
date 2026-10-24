"""Read-only preflight: verify Supabase backup table is accessible.

No trades, no Gist changes, and no database writes.
"""
import os
import requests

def main():
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key
    url = base + "/rest/v1/bot_state_backups"
    response = requests.get(url, headers=headers, params={"select": "bot,revision", "limit": "10"}, timeout=20)
    if response.status_code != 200:
        raise RuntimeError("Backup table preflight failed: HTTP " + str(response.status_code))
    rows = response.json()
    if not isinstance(rows, list):
        raise RuntimeError("Unexpected backup table response")
    print("Backup table accessible. Returned", len(rows), "metadata rows.")
    print("No trading state read or changed.")

if __name__ == "__main__":
    main()
