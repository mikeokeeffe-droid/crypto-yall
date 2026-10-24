"""Manual, backup-only snapshot with independent readback and explicit verification.

Never changes Gists, live bot_state, orders or strategy. Requires coordinated
snapshot window with bot writers paused and exchange-side protection verified.
"""
import hashlib
import datetime as dt
import json
import os
import sys
import uuid
import requests

SOURCES = (
    ("aggressive", "AGGRESSIVE_GIST_ID", "aggressive_state.json"),
    ("intraday", "INTRADAY_GIST_ID", "intraday_state.json"),
    ("daily", "GIST_ID", "crypto_yall_state.json"),
)


def canonical(value):
    if not isinstance(value, dict):
        raise ValueError("State must be a JSON object")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def gist_read(session, gist_id, filename, token):
    headers = {"Authorization": "token " + token}
    response = session.get("https://api.github.com/gists/" + gist_id, headers=headers, timeout=30)
    response.raise_for_status()
    doc = response.json()
    item = doc["files"][filename]
    if item.get("truncated"):
        raw = session.get(item["raw_url"], headers=headers, timeout=30)
        raw.raise_for_status()
        body = raw.text
    else:
        body = item["content"]
    state = json.loads(body)
    canonical(state)
    # GitHub Gist history version identifies the observed source revision.
    version = doc["history"][0]["version"]
    return state, version


def read_snapshot(session, base, headers, snapshot_id):
    response = session.get(
        base + "/rest/v1/bot_state_snapshots",
        headers=headers,
        params={"snapshot_id": "eq." + snapshot_id, "select": "state,verified"},
        timeout=30,
    )
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or len(rows) != 1:
        raise RuntimeError("Snapshot readback not unique")
    return rows[0]


def main():
    if os.getenv("SNAPSHOT_WINDOW_CONFIRMED") != "YES":
        raise RuntimeError("Coordinated snapshot window not confirmed")
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key
    token = os.environ["GIST_TOKEN"]
    session = requests.Session()

    for bot, env, filename in SOURCES:
        gist_id = os.environ[env]
        original, version = gist_read(session, gist_id, filename, token)
        expected_digest = digest(original)
        snapshot_id = str(uuid.uuid4())
        payload = {"snapshot_id": snapshot_id, "bot": bot,
                   "source_gist_id": gist_id, "source_gist_version": version,
                   "source_sha256": expected_digest, "state": original}
        # If POST times out, never blindly retry: query by UUID to resolve.
        try:
            response = session.post(
                base + "/rest/v1/bot_state_snapshots",
                headers=headers, json=payload, timeout=30)
            response.raise_for_status()
        except requests.RequestException:
            row = read_snapshot(session, base, headers, snapshot_id)
            if digest(row["state"]) != expected_digest:
                raise RuntimeError(bot + ": ambiguous write mismatch")
        row = read_snapshot(session, base, headers, snapshot_id)
        if row["verified"] or digest(row["state"]) != expected_digest:
            raise RuntimeError(bot + ": readback mismatch or unexpected verified flag")
        latest, latest_version = gist_read(session, gist_id, filename, token)
        if latest_version != version or digest(latest) != expected_digest:
            raise RuntimeError(bot + ": source changed; snapshot remains unverified")
        # Only verified after independent readback AND source version comparison.
        try:
            update = session.patch(
                base + "/rest/v1/bot_state_snapshots",
                headers={**headers, "Prefer": "return=representation"},
                params={"snapshot_id": "eq." + snapshot_id, "verified": "eq.false"},
                json={"verified": True, "verified_at": dt.datetime.now(dt.timezone.utc).isoformat()},
                timeout=30,
            )
            update.raise_for_status()
            result = update.json()
            if not isinstance(result, list) or len(result) != 1:
                raise RuntimeError(bot + ": verification status not confirmed")
        except (requests.RequestException, ValueError):
            # Ambiguous PATCH outcome: read back, never repeat the mutation.
            confirmed = read_snapshot(session, base, headers, snapshot_id)
            if confirmed.get("verified") is not True or digest(confirmed["state"]) != expected_digest:
                raise RuntimeError(bot + ": verification could not be confirmed")
        # Independently verify final persisted state, even after a 2xx response.
        confirmed = read_snapshot(session, base, headers, snapshot_id)
        if confirmed.get("verified") is not True or digest(confirmed["state"]) != expected_digest:
            raise RuntimeError(bot + ": final snapshot verification failed")
        print(bot + ": snapshot readback and source version verified")
    print("Three snapshots verified. Live bot state untouched.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Snapshot failed: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
