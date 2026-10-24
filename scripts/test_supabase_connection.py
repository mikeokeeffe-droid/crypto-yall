"""Read-only Supabase connectivity smoke test. Never places orders or writes state."""
import os
import sys
import requests

def main():
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    if not url.startswith("https://") or ".supabase.co" not in url:
        raise ValueError("Invalid Supabase URL")
    if not key.startswith(("sb_secret_", "eyJ")):
        raise ValueError("Unexpected Supabase secret key format")
    headers = {"apikey": key}
    # Modern sb_secret_* keys authenticate via apikey; legacy JWT keys also
    # require a Bearer token for PostgREST.
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    # Request no rows, only verify the table exists and privileged credentials work.
    response = requests.get(
        f"{url}/rest/v1/bot_state",
        headers={**headers, "Range": "0-0"},
        params={"select": "bot", "limit": "0"},
        timeout=15,
    )
    if response.status_code != 200:
        print(f"Supabase connection FAILED (HTTP {response.status_code}); response body suppressed")
        return 1
    print("Supabase connection OK; bot_state table accessible (read-only)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
