"""Read-only audit of existing bot state files.

This script never writes to Gists, Supabase, or Hyperliquid.
It reports only JSON shape, key names, and a content digest.
"""
import hashlib
import json
import os
import sys
import requests

SOURCES = {
    "aggressive": ("AGGRESSIVE_GIST_ID", "aggressive_state.json"),
    "intraday": ("INTRADAY_GIST_ID", "intraday_state.json"),
}

def audit(bot, token):
    env, filename = SOURCES[bot]
    gist_id = os.environ[env]
    headers = {"Authorization": "token " + token}
    response = requests.get("https://api.github.com/gists/" + gist_id, headers=headers, timeout=30)
    response.raise_for_status()
    entry = response.json()["files"][filename]
    if entry.get("truncated"):
        raw = requests.get(entry["raw_url"], headers=headers, timeout=30)
        raw.raise_for_status()
        contents = raw.text
    else:
        contents = entry["content"]
    state = json.loads(contents)
    if not isinstance(state, dict):
        raise ValueError("Expected a JSON object")
    digest = hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    print(f"{bot}: valid JSON, {len(state)} top-level keys, sha256={digest}")
    print(f"{bot}: top-level field names: {', '.join(sorted(state))}")

def main():
    token = os.environ["GIST_TOKEN"]
    for bot in SOURCES:
        audit(bot, token)
    print("Read-only audit complete. No state was modified.")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Audit failed: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)
