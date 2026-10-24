"""Read-only final Gist versus verified Supabase snapshot comparison."""
import hashlib
import json
import os
import sys
import requests

SOURCES = (
    ("aggressive", "AGGRESSIVE_GIST_ID", "aggressive_state.json"),
    ("intraday", "INTRADAY_GIST_ID", "intraday_state.json"),
    ("daily", "GIST_ID", "crypto_yall_state.json"),
)

def digest(value):
    if not isinstance(value, dict):
        raise ValueError("State must be a JSON object")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

def main():
    session = requests.Session()
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key}
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key
    gist_headers = {"Authorization": "token " + os.environ["GIST_TOKEN"]}
    ok = True
    for bot, env, filename in SOURCES:
        gist_id = os.environ[env]
        response = session.get("https://api.github.com/gists/" + gist_id, headers=gist_headers, timeout=30)
        response.raise_for_status()
        gist = response.json()
        file = gist["files"][filename]
        if file.get("truncated"):
            raw = session.get(file["raw_url"], headers=gist_headers, timeout=30)
            raw.raise_for_status()
            body = raw.text
        else:
            body = file["content"]
        current_hash = digest(json.loads(body))
        current_version = gist["history"][0]["version"]
        response = session.get(base + "/rest/v1/bot_state_snapshots", headers=headers, params={
            "select": "snapshot_id,source_gist_id,source_gist_version,source_sha256,state,verified,verified_at",
            "bot": "eq." + bot, "verified": "eq.true", "order": "verified_at.desc", "limit": "1000"
        }, timeout=30)
        response.raise_for_status()
        rows = response.json()
        matches = [row for row in rows if row.get("source_gist_id") == gist_id
                   and row.get("source_gist_version") == current_version
                   and row.get("source_sha256") == current_hash
                   and row.get("verified_at") is not None
                   and digest(row["state"]) == current_hash]
        if len(matches) == 1:
            print("PASS " + bot + ": latest Gist version and content match exactly one verified snapshot; snapshot_id=" + matches[0]["snapshot_id"])
        else:
            ok = False
            print("NOT READY " + bot + ": expected exactly one matching verified snapshot, found " + str(len(matches)))
    if not ok:
        raise RuntimeError("One or more bots lack an unambiguous current snapshot")
    print("READ-ONLY comparison passed. No Gist, Supabase state or exchange writes.")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Read-only comparison failed: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
