"""Manual, backup-only Gist snapshot with independent Supabase readback.

Does not update Gists, bot_state, orders, or live trading logic.
"""
import hashlib
import json
import os
import sys
import time

import requests

SOURCES = (
    ("aggressive", "AGGRESSIVE_GIST_ID", "aggressive_state.json"),
    ("intraday", "INTRADAY_GIST_ID", "intraday_state.json"),
    ("daily", "GIST_ID", "crypto_yall_state.json"),
)


def canonical(state):
    if not isinstance(state, dict):
        raise ValueError("State must be a JSON object")
    return json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def gist_read(session, gist_id, filename, token):
    headers = {"Authorization": "token " + token}
    response = session.get("https://api.github.com/gists/" + gist_id, headers=headers, timeout=30)
    response.raise_for_status()
    item = response.json()["files"][filename]
    if item.get("truncated"):
        raw = session.get(item["raw_url"], headers=headers, timeout=30)
        raw.raise_for_status()
        body = raw.text
    else:
        body = item["content"]
    return json.loads(body)


def main():
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key, "Content-Type": "application/json", "Prefer": "return=representation"}
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key
    token = os.environ["GIST_TOKEN"]
    session = requests.Session()

    for bot, env, filename in SOURCES:
        gist_id = os.environ[env]
        original = gist_read(session, gist_id, filename, token)
        digest = hashlib.sha256(canonical(original)).hexdigest()
        # Timestamp is a unique snapshot identifier, not the live bot_state revision.
        snapshot_id = time.time_ns()
        url = base + "/rest/v1/bot_state_backups"
        payload = {"bot": bot, "revision": snapshot_id, "state": original}
        written = session.post(url, headers=headers, json=payload, timeout=30)
        written.raise_for_status()
        readback = session.get(url, headers={"apikey": key, **({"Authorization": "Bearer " + key} if key.startswith("eyJ") else {})},
                               params={"bot": "eq." + bot, "revision": "eq." + str(snapshot_id), "select": "state"}, timeout=30)
        readback.raise_for_status()
        rows = readback.json()
        if len(rows) != 1 or hashlib.sha256(canonical(rows[0]["state"])).hexdigest() != digest:
            raise RuntimeError(bot + ": saved backup does not match snapshot")
        latest = gist_read(session, gist_id, filename, token)
        if hashlib.sha256(canonical(latest)).hexdigest() != digest:
            raise RuntimeError(bot + ": Gist changed during backup; snapshot is not current")
        print(bot + ": backup saved, readback verified, source unchanged during snapshot")
    print("All three backup snapshots verified. Live trading state untouched.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Backup failed: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
